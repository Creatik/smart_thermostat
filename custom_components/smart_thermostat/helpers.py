"""Чистые вспомогательные функции (без зависимостей от Home Assistant)."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any, Optional

_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")

# Дефолты (дублируют const — helpers импортируются без HA).
_SOFT_LANDING_FLOOR = 0.3
_SOFT_LANDING_SPAN_MULT = 2.0
_SOFT_LANDING_SPAN_MIN = 1.0
_UNDERHEAT_TRV_MARGIN = 0.8
_OVERSHOOT_TRV_MARGIN = 0.5
_HEAT_FLOW_LOCAL_MARGIN = 1.5
_APPROACH_BAND_MULT = 2.0
_APPROACH_BAND_MIN = 1.0
_APPROACH_PREDICT_MAX_MIN = 12.0
_APPROACH_RATE_MIN = 0.01
_APPROACH_RISE_RATE_MIN = 0.005
_APPROACH_RISE_DT_MIN = 1.0
_OFFSET_TRIM_SOFT_TRIGGER = 2.0
_OFFSET_TRIM_MAX = 0.5
_OFFSET_SATURATED_TRIGGER = 3.0


def clamp(v: float, lo: float, hi: float) -> float:
    """Ограничить значение диапазоном [lo, hi]."""
    return max(lo, min(hi, v))


def heating_rate_sample(
    dT: float,
    dt_min: float,
    *,
    dt_min_lo: float = 0.25,
    dt_min_hi: float = 30.0,
    dtemp_min: float = 0.01,
    rate_lo: float = 0.002,
    rate_hi: float = 0.25,
) -> float | None:
    """Мгновенная скорость нагрева °C/мин или None (шум / охлаждение / bad dt).

    Только рост температуры: отрицательный dT (сквозняк) не усредняем.
    """
    if dt_min <= 0 or dt_min < dt_min_lo or dt_min > dt_min_hi:
        return None
    if dT < dtemp_min:
        return None
    rate = dT / dt_min
    if rate < rate_lo or rate > rate_hi:
        return None
    return rate


def ema_heating_rate(prev: float, sample: float, alpha: float) -> float:
    """EMA: rate ← α·sample + (1−α)·prev."""
    a = clamp(float(alpha), 0.0, 1.0)
    return a * float(sample) + (1.0 - a) * float(prev)


def predicted_minutes_to_target(
    error: float | None,
    *,
    minutes_per_degree: float | None = None,
    heating_rate: float | None = None,
    deadband: float = 0.5,
    mpd_lo: float = 2.0,
    mpd_hi: float = 120.0,
    rate_lo: float = 0.002,
) -> float:
    """Минуты до входа в deadband при выученном темпе нагрева.

    Старая формула ``error / heating_rate`` врала:
    - tick-rate легко завышен (0.12°C/мин → «2 мин до цели»);
    - ``minutes_per_degree`` из TTT-эпизодов игнорировался и разъезжался;
    - считали до exact target, хотя контур уже в deadband «у цели».

    Приоритет: mpd (TTT) → fallback ``1/rate``. Если оба есть — среднее
    геометрическое (гасит пики rate и завышенный старый mpd).
    """
    if error is None:
        return 0.0
    try:
        e = float(error)
    except (TypeError, ValueError):
        return 0.0
    if e <= 0:
        return 0.0

    remaining = e - max(0.0, float(deadband))
    if remaining <= 1e-9:
        return 0.0

    mpd_ttt: float | None = None
    if minutes_per_degree is not None:
        try:
            v = float(minutes_per_degree)
            if v > 0:
                mpd_ttt = v
        except (TypeError, ValueError):
            mpd_ttt = None

    mpd_rate: float | None = None
    if heating_rate is not None:
        try:
            r = float(heating_rate)
            if r > float(rate_lo):
                mpd_rate = 1.0 / r
        except (TypeError, ValueError):
            mpd_rate = None

    if mpd_ttt is not None and mpd_rate is not None:
        mpd = (mpd_ttt * mpd_rate) ** 0.5
    elif mpd_ttt is not None:
        mpd = mpd_ttt
    elif mpd_rate is not None:
        mpd = mpd_rate
    else:
        return 0.0

    mpd = clamp(mpd, float(mpd_lo), float(mpd_hi))
    return round(remaining * mpd, 1)


def soft_landing_factor(
    error: float,
    deadband: float,
    *,
    floor: float = _SOFT_LANDING_FLOOR,
    span_mult: float = _SOFT_LANDING_SPAN_MULT,
    span_min: float = _SOFT_LANDING_SPAN_MIN,
) -> float:
    """Множитель PID при мягкой посадке к уставке (только нагрев, error > 0).

    В полосе ``deadband … deadband + ease_span`` плавно гасит коррекцию
    от 1.0 до ``floor``. Батарея остывает медленно: ранняя посадка
    использует остаточное тепло и режет перегрев. Пол не нулевой —
    иначе у края deadband контур голодает и недогревает.

    Вне полосы и при error ≤ 0 → 1.0 (перегрев ведёт клапан/hold).
    """
    if error <= 0 or deadband < 0:
        return 1.0
    ease_span = max(span_min, span_mult * deadband)
    if ease_span <= 0:
        return 1.0
    if error >= deadband + ease_span:
        return 1.0
    return clamp((error - deadband) / ease_span, floor, 1.0)


def apply_soft_landing(
    correction: float,
    error: float,
    deadband: float,
    *,
    floor: float = _SOFT_LANDING_FLOOR,
    span_mult: float = _SOFT_LANDING_SPAN_MULT,
    span_min: float = _SOFT_LANDING_SPAN_MIN,
) -> float:
    """Применить мягкую посадку к PID-коррекции."""
    return correction * soft_landing_factor(
        error,
        deadband,
        floor=floor,
        span_mult=span_mult,
        span_min=span_min,
    )


def valve_heat_demand(error: float, deadband: float) -> bool | None:
    """Нужен ли нагрев по клапану с учётом инерции радиатора.

    Приоритет: **не допускать недогрев**; лёгкий перегрев терпим
    (батарея остывает медленно — остаточное тепло ещё идёт после закрытия).

    - ``True`` — открыть при недогреве выше шумового пола.
    - ``False`` — закрыть уже при небольшом перелёте цели (не ждать
      −deadband: иначе инерция гарантированно перегреет сильнее).
    - ``None`` — |error| ≤ noise: не дёргать клапан.
    """
    noise = min(0.1, max(0.05, abs(deadband) * 0.2))
    if error > noise:
        return True
    if error < -noise:
        return False
    return None


def underheat_trv_floor(
    t_room: float,
    error: float,
    deadband: float,
    margin: float = _UNDERHEAT_TRV_MARGIN,
) -> float | None:
    """Нижняя граница уставки TRV при недогреве, иначе None.

    Любой недогрев (error > 0), не только за deadband: иначе при
    e=0.4 / deadband=0.5 и offset≈−3 уставка TRV < room и клапан
    закрыт («цель выше, батарея холодная» — гостиная 96% TRV<room).
    ``deadband`` зарезервирован для совместимости вызова.
    """
    _ = deadband
    if error > 0:
        return float(t_room) + float(margin)
    return None


def overshoot_trv_ceiling(
    t_room: float,
    error: float,
    deadband: float,
    margin: float = _OVERSHOOT_TRV_MARGIN,
) -> float | None:
    """Верхняя граница уставки TRV при перелёте цели, иначе None.

    Срабатывает при явном перегреве (error < −noise), не при |e|≈0:
    у цели нужен равновесный target+offset. При перелёте уставка выше
    комнаты держит клапан «на взводе»: local TRV остывает → set > local
    → снова горячая батарея при idle (спальня 23.6 / TRV 25).
    """
    noise = min(0.1, max(0.05, abs(deadband) * 0.2))
    if error < -noise:
        return float(t_room) - float(margin)
    return None


def room_is_rising(
    prev_room_temp: float | None,
    prev_time_mono: float | None,
    now_mono: float,
    t_room: float,
    *,
    rate_min: float = _APPROACH_RISE_RATE_MIN,
    dt_min_lo: float = _APPROACH_RISE_DT_MIN,
) -> bool:
    """Комната реально растёт между двумя наблюдениями.

    Evidence-гвард ранней посадки: ``heating_rate`` — EMA и переживает часы
    покоя, а посадка/trim на остывающей комнате дают недогрев (хуже перелёта).
    Порог в °C/мин, а не в °C за интервал: спальня на подходе растёт
    ~0.04 °C за 4-минутный тик (0.01 °C/мин), а квант датчика 0.01 °C на
    коротком интервале выглядел бы как «рост».
    """
    if prev_room_temp is None or prev_time_mono is None:
        return False
    try:
        dt_min = (float(now_mono) - float(prev_time_mono)) / 60.0
        dtemp = float(t_room) - float(prev_room_temp)
    except (TypeError, ValueError):
        return False
    if dt_min < float(dt_min_lo) or dtemp <= 0:
        return False
    return (dtemp / dt_min) >= float(rate_min)


def local_is_rising(
    prev_local: float | None,
    prev_time_mono: float | None,
    now_mono: float,
    t_local: float | None,
    *,
    rate_min: float = _APPROACH_RISE_RATE_MIN,
    dt_min_lo: float = _APPROACH_RISE_DT_MIN,
) -> bool:
    """Батарея сама теплеет между тиками.

    Рост комнаты при холодном или отсутствующем local — не запас чугуна:
    солнце на датчике комнаты даёт ту же картину. Предиктивная посадка
    имеет право сработать только когда теплеет сам клапан.
    """
    if t_local is None:
        return False
    return room_is_rising(
        prev_local,
        prev_time_mono,
        now_mono,
        t_local,
        rate_min=rate_min,
        dt_min_lo=dt_min_lo,
    )


def offset_write_within_budget(
    current: float,
    proposed: float,
    *,
    spent: float = 0.0,
    max_step: float = 0.3,
    min_change: float = 0.1,
) -> float | None:
    """Новый offset в пределах остатка max_offset_step за тик, иначе None.

    ``spent`` — уже записанный в этом тике |Δoffset|. Сумма с новым шагом
    не больше ``max_step``: approach_trim и decay не складываются.
    """
    try:
        cur = float(current)
        prop = float(proposed)
        budget = max(0.0, abs(float(max_step)) - abs(float(spent)))
        floor = abs(float(min_change))
    except (TypeError, ValueError):
        return None
    if budget < floor - 1e-9:
        return None
    delta = prop - cur
    if delta > budget:
        delta = budget
    elif delta < -budget:
        delta = -budget
    if abs(delta) < floor - 1e-9:
        return None
    return cur + delta


def approach_predict_landing(
    error: float,
    deadband: float,
    *,
    heating_rate: float | None = None,
    minutes_per_degree: float | None = None,
    room_rising: bool = False,
    local_rising: bool = False,
    predict_max_min: float = _APPROACH_PREDICT_MAX_MIN,
    rate_min: float = _APPROACH_RATE_MIN,
) -> bool:
    """Предиктивная отсечка: «долетим до цели за N минут — садимся сейчас».

    Второй (после «горячего local») признак ранней посадки. Нужен, когда
    local ещё не дотянул до порога «горячо», но сам уже растёт: тепло пошло
    в батарею, датчик просто отстаёт.

    Рост только комнаты не считается: солнце на комнатном датчике при
    холодном или отсутствующем local дало бы срез уставки и approach_trim,
    а offset вниз уже не вернуть. Нужны оба факта — ``room_rising`` и
    ``local_rising``.
    """
    try:
        if float(predict_max_min) <= 0 or not room_rising or not local_rising:
            return False
        rate = float(heating_rate) if heating_rate is not None else None
    except (TypeError, ValueError):
        return False
    if rate is None or rate < float(rate_min):
        return False
    mpd = None
    if minutes_per_degree is not None:
        try:
            mpd = float(minutes_per_degree)
        except (TypeError, ValueError):
            mpd = None
    eta = predicted_minutes_to_target(
        error,
        minutes_per_degree=mpd,
        heating_rate=rate,
        deadband=deadband,
    )
    return eta <= float(predict_max_min)


def approach_trv_ceiling(
    t_room: float,
    error: float,
    deadband: float,
    t_local: float | None,
    *,
    t_target: float | None = None,
    local_margin: float = _HEAT_FLOW_LOCAL_MARGIN,
    approach_band_mult: float = _APPROACH_BAND_MULT,
    approach_band_min: float = _APPROACH_BAND_MIN,
    trv_margin: float = _UNDERHEAT_TRV_MARGIN,
    heating_rate: float | None = None,
    minutes_per_degree: float | None = None,
    room_rising: bool = False,
    local_rising: bool = False,
    predict_max_min: float = 0.0,
    rate_min: float = _APPROACH_RATE_MIN,
) -> float | None:
    """Потолок TRV на подходе к цели при уже горячей батарее.

    Пока ещё недогрев (``error > 0``), но ошибка уже в полосе мягкой
    посадки и батарея горячая — не держать ``target+offset`` далеко
    выше room. Soft-landing PID этого не режет (offset остаётся).
    Факт: спальня 04.11 room≈23 / TRV 26 / local 24+ → пик 24.3.

    «Горячая батарея»: ``local ≥ room+margin`` ИЛИ ``local ≥ t_target``
    (радиатор уже на цели — остаточного тепла хватит добить e; иначе
    порог room+1.5 срабатывает слишком поздно).

    Если local ещё не горячий, но сам растёт и комната по rate/TTT долетит
    до цели за ``predict_max_min`` минут — тоже садимся
    (см. ``approach_predict_landing``). Холодный или отсутствующий local
    при росте только комнаты потолок не даёт. По умолчанию
    ``predict_max_min=0`` — ветка выключена, поведение прежнее.

    Потолок = ``room + trv_margin`` (= underheat floor): срезаем лишнее,
    инвариант недогрева не ломаем.
    """
    try:
        e = float(error)
        db = abs(float(deadband))
        room = float(t_room)
    except (TypeError, ValueError):
        return None
    if e <= 0:
        return None
    ease = max(float(approach_band_min), float(approach_band_mult) * db)
    if e > db + ease + 1e-9:
        return None
    hot = False
    have_local = False
    if t_local is not None:
        try:
            local = float(t_local)
        except (TypeError, ValueError):
            local = None
        if local is not None:
            have_local = True
            hot = trv_heat_flowing(room, local, margin=local_margin)
            if not hot and t_target is not None:
                try:
                    hot = local >= float(t_target) - 1e-9
                except (TypeError, ValueError):
                    hot = False
    if not hot and not approach_predict_landing(
        e,
        db,
        heating_rate=heating_rate,
        minutes_per_degree=minutes_per_degree,
        room_rising=room_rising,
        local_rising=local_rising and have_local,
        predict_max_min=predict_max_min,
        rate_min=rate_min,
    ):
        return None
    return room + float(trv_margin)


def approach_offset_toward(
    offset: float,
    t_room: float,
    t_target: float,
    *,
    trv_margin: float = _UNDERHEAT_TRV_MARGIN,
    max_step: float = 0.3,
    min_change: float = 0.1,
) -> float:
    """Сдвинуть offset к равновесию ранней посадки (не больше max_step).

    Потолок TRV = room+margin ⇒ равновесный offset ≈ margin − error.
    Пока текущий offset выше — шаг вниз, иначе значение не меняем.
    Без этого каждый тик снова считает target+offset ≫ потолка.
    """
    try:
        cur = float(offset)
        implied = float(t_room) + float(trv_margin) - float(t_target)
        step = abs(float(max_step))
        floor = abs(float(min_change))
    except (TypeError, ValueError):
        return offset
    if cur <= implied + floor:
        return cur
    return max(implied, cur - step)


# Состояния «кто-то дома» для person / device_tracker / binary_sensor
_OCCUPANCY_HOME_STATES = frozenset(
    {"home", "on", "true", "present", "open", "1", "yes"}
)
# Активность: свет, розетка чайника, motion, media
_OCCUPANCY_ACTIVE_STATES = frozenset(
    {
        "on",
        "true",
        "1",
        "open",
        "playing",
        "home",
        "detected",
        "motion",
        "occupied",
    }
)


def state_means_home(state: Any) -> bool:
    """person.*/tracker: дома ли человек (зона home / on)."""
    if state is None:
        return False
    return str(state).strip().lower() in _OCCUPANCY_HOME_STATES


def state_means_activity(state: Any) -> bool:
    """Свет / чайник / motion / media — признак «дома кто-то есть»."""
    if state is None:
        return False
    return str(state).strip().lower() in _OCCUPANCY_ACTIVE_STATES


def arrival_slot_kind(minutes_since_midnight: int) -> str | None:
    """Утро 04–12 / вечер 14–24; иначе шум (не для графика)."""
    m = int(minutes_since_midnight)
    if 4 * 60 <= m < 12 * 60:
        return "morning"
    if 14 * 60 <= m < 24 * 60:
        return "evening"
    return None


def median_int(values: list[int]) -> int | None:
    if not values:
        return None
    s = sorted(int(v) for v in values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def predict_arrival_minutes(
    history: list[dict],
    weekday: int,
    slot: str,
    *,
    min_samples: int = 3,
) -> int | None:
    """Медиана минут прихода для weekday+slot; fallback — все дни этого слота."""
    same = [
        int(h["minutes"])
        for h in history
        if h.get("slot") == slot and int(h.get("weekday", -1)) == int(weekday)
    ]
    if len(same) >= min_samples:
        return median_int(same)
    any_day = [int(h["minutes"]) for h in history if h.get("slot") == slot]
    if len(any_day) >= min_samples:
        return median_int(any_day)
    return None


def in_learned_preheat_window(
    now_minutes: int,
    typical_arrival_minutes: int,
    lead_min: int,
) -> bool:
    """Окно [typical − lead, typical): греть до ожидаемого прихода."""
    lead = int(lead_min or 0)
    if lead <= 0:
        return False
    now_m = int(now_minutes) % (24 * 60)
    ready = int(typical_arrival_minutes) % (24 * 60)
    start = (ready - lead) % (24 * 60)
    if start < ready:
        return start <= now_m < ready
    # через полночь
    return now_m >= start or now_m < ready


def merge_occupancy(
    *,
    person_home: bool | None,
    activity_on: bool,
    activity_hold_active: bool,
    has_person_sensors: bool,
    has_activity_sensors: bool,
) -> bool:
    """Слить person + активность в один флаг «дома есть кто-то».

    - Нет ни person, ни activity → True (не душить нагрев без датчиков).
    - Только person → по зоне home / not_home / «на работе».
    - Только activity → on или hold после выключения чайника/света.
    - Оба → OR (GPS ещё «работа», а чайник уже включили — дома).
    """
    if not has_person_sensors and not has_activity_sensors:
        return True
    activity = activity_on or activity_hold_active
    if has_person_sensors and has_activity_sensors:
        return bool(person_home) or activity
    if has_person_sensors:
        return bool(person_home)
    return activity


def parse_hhmm(value: Any) -> time | None:
    """Разобрать 'HH:MM' / datetime.time / пусто → None."""
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    s = str(value).strip()
    m = _HHMM_RE.match(s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return time(h, mi)


def _as_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def in_preheat_before_ready(
    now: datetime,
    ready_hhmm: Any,
    lead_min: int,
) -> bool:
    """Окно предпрогрева: [ready − lead, ready).

    «Батареи тёплые к 06:30, lead=45» → греем 05:45–06:30.
    Пустой ready или lead≤0 → выкл.
    """
    ready = parse_hhmm(ready_hhmm)
    lead = int(lead_min or 0)
    if ready is None or lead <= 0:
        return False
    ready_dt = datetime.combine(now.date(), ready)
    if now.tzinfo is not None:
        ready_dt = ready_dt.replace(tzinfo=now.tzinfo)
    start_dt = ready_dt - timedelta(minutes=lead)
    if start_dt <= now < ready_dt:
        return True
    # Окно через полночь: ready рано утром, «сейчас» ещё до полуночи вчера
    ready_y = ready_dt - timedelta(days=1)
    start_y = ready_y - timedelta(minutes=lead)
    return start_y <= now < ready_y


def active_preheat_slot(
    now: datetime,
    morning_ready: Any,
    evening_ready: Any,
    lead_min: int,
    *,
    is_workday: bool | None = None,
    morning_ready_weekend: Any = None,
    evening_on_weekend: bool = False,
) -> str | None:
    """Какой слот предпрогрева активен: 'morning' | 'evening' | None.

    Под HA automation пользователя:
    - будни: комфорт 05–07 и 18–23 → preheat к 05:00 и к 18:00;
    - выходные: комфорт 07–23 → preheat к 07:00, вечерний не нужен.
    ``is_workday is None`` (нет датчика) — оба слота по будничным ready.
    """
    morning = morning_ready
    if is_workday is False and morning_ready_weekend not in (None, ""):
        morning = morning_ready_weekend
    if in_preheat_before_ready(now, morning, lead_min):
        return "morning"
    if is_workday is False and not evening_on_weekend:
        return None
    if in_preheat_before_ready(now, evening_ready, lead_min):
        return "evening"
    return None


def in_night_no_learn_window(
    now: datetime,
    start_hhmm: Any = "22:00",
    end_hhmm: Any = "05:00",
) -> bool:
    """Ночное окно без обучения (открытые окна без датчиков).

    По умолчанию 22:00–05:00: ночной холод от форточки не должен
    разгонять offset.
    """
    start = parse_hhmm(start_hhmm)
    end = parse_hhmm(end_hhmm)
    if start is None or end is None:
        return False
    cur = now.hour * 60 + now.minute
    s, e = _as_minutes(start), _as_minutes(end)
    if s == e:
        return False
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e


def round_step(v: float, step: float) -> float:
    """Округлить до ближайшего кратного step."""
    if step <= 0:
        return v
    return round(v / step) * step


def to_float(value: Any) -> Optional[float]:
    """Преобразовать значение (state/attr) в float.

    Возвращает None для unknown/unavailable/пустых/непарсящихся значений.
    Принимает строки вида: "22.5", "22,5", "22.5 °C", "temp: 22,5" и т.п.
    """
    if value is None:
        return None

    # Быстрый путь для чисел
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        # Отсекаем NaN/inf
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f

    s = str(value).strip().lower()
    if s in ("unavailable", "unknown", "none", "", "uninitialized", "nan", "null"):
        return None

    m = _NUM_RE.search(s)
    if not m:
        return None

    num = m.group(0).replace(",", ".")
    try:
        f = float(num)
    except (TypeError, ValueError):
        return None

    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def usable_trv_local(
    value: float | None,
    *,
    lo: float = 5.0,
    hi: float = 45.0,
) -> float | None:
    """Температура головы TRV или None, если датчик врёт.

    Радиатор в отопительный сезон не бывает −0.01 и не бывает за пределом
    hi. Такое значение нельзя кормить посадке и холодному старту.
    """
    if value is None:
        return None
    try:
        v = float(value)
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None
    if v != v or v < lo_f or v > hi_f:
        return None
    return v


def local_is_stuck(
    flat_sec: float,
    set_span: float,
    *,
    stuck_after_sec: float,
    min_set_span: float,
    commanded_above: bool = False,
    command_stuck_sec: float = 1800,
) -> bool:
    """Полка local — датчик завис, не радиатор.

    Либо уставка за это время заметно гуляла, либо всё окно уставка была
    намного выше local (команда «грей», датчик нем). Ровное удержание
    около самого local полкой не считается.
    """
    try:
        flat = float(flat_sec)
        if commanded_above and flat >= float(command_stuck_sec):
            return True
        return flat >= float(stuck_after_sec) and float(set_span) >= float(min_set_span)
    except (TypeError, ValueError):
        return False


def weather_suppressed(
    latched: bool,
    at_max: bool,
    below_release: bool,
    room_short: bool = True,
) -> bool:
    """Держать погодную надбавку выключенной, пока она только дёргает клапан.

    Включаем снова, только если уставка отошла от максимума И комната
    реально ниже карточки. Иначе посадка срезает set 30→23.5 при воздухе
    уже у цели, защёлка отпускает надбавку, и уставка снова бьётся в 30
    (гостиная 08.11, 93 переключения за сутки).
    """
    if at_max:
        return True
    if latched and not (below_release and room_short):
        return True
    return False


def ttt_sample_mpd(
    minutes: float,
    rise: float,
    *,
    min_minutes: float,
    min_rise: float,
    mpd_lo: float,
    mpd_hi: float,
) -> float | None:
    """Минуты на градус по эпизоду нагрева.

    None — эпизод короче физики радиатора (0 минут, подъём из пола 0.1°).
    Такую выборку нельзя зажимать в нижний предел: детская 08.11 так
    получила mpd=2 вместо ~40 и испортила прогноз посадки.
    """
    try:
        mins = float(minutes)
        gained = float(rise)
        if mins < float(min_minutes) or gained < float(min_rise):
            return None
        mpd = mins / gained
        lo = float(mpd_lo)
        hi = float(mpd_hi)
        if mpd < lo or mpd > hi:
            return None
        return mpd
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def blend_minutes_per_degree(
    current: float,
    heating_rate: float,
    *,
    mpd_min: float = 8.0,
    mpd_max: float = 120.0,
    weight: float = 0.15,
) -> float | None:
    """Подтянуть память мин/°C к 1/rate.

    Если в памяти уже выброс (ниже пола), не усредняем с ним — берём темп.
    """
    try:
        rate = float(heating_rate)
        if rate <= 0:
            return None
        sample = clamp(1.0 / rate, float(mpd_min), float(mpd_max))
        cur = float(current)
    except (TypeError, ValueError):
        return None
    if cur < float(mpd_min):
        return sample
    w = clamp(float(weight), 0.0, 1.0)
    return w * sample + (1.0 - w) * cur


def trv_heat_flowing(
    t_room: float,
    t_local: float | None,
    *,
    margin: float = 1.5,
) -> bool:
    """Локальная TRV заметно теплее комнаты → вода/клапан реально греют."""
    if t_local is None:
        return False
    try:
        return float(t_local) >= float(t_room) + float(margin)
    except (TypeError, ValueError):
        return False


def valve_ref_setpoint(
    learn_direction: int,
    last_set: float | None,
    desired: float,
) -> float:
    """Опорная уставка для гварда «клапан без власти».

    «Худшая» для направления оценка: вверх — ``max(last_set, desired)``,
    вниз — ``min(...)``. ``last_set`` отстаёт на тик (Zigbee) и затирается
    низким reported при mismatch, но уже содержит PID прошлого тика;
    ``desired`` (t_effective+offset) этого тика — без PID, при e>0 это
    нижняя граница. ``last_set`` None (первые тики) → ``desired``.
    Битые значения → ``desired`` (консервативно).
    """
    try:
        des = float(desired)
    except (TypeError, ValueError):
        return 0.0
    if last_set is None:
        return des
    try:
        last = float(last_set)
    except (TypeError, ValueError):
        return des
    if learn_direction > 0:
        return max(last, des)
    if learn_direction < 0:
        return min(last, des)
    return des


def valve_learning_blocked(
    learn_direction: int,
    ref_setpoint: float,
    t_local: float | None,
    t_room: float | None,
    *,
    travel_margin: float = 2.0,
    heat_margin: float = 1.5,
) -> bool:
    """True, если клапан уже на пределе хода и учить offset дальше бессмысленно.

    TRV открывается пропорционально (уставка − local): при уставке выше
    ``local + travel_margin`` клапан уже полностью открыт — поднимать offset
    некуда, батарея больше тепла не даст. Если при этом тепло НЕ течёт
    (local ≈ room — котёл/циркуляция не дают), обучение вверх чистый
    самообман: offset улетает к +6 и позже выстреливает перегревом
    (детская 02.11: 1.8→+6 за час при мёртвой комнате 22.3).
    Когда тепло течёт — обучение вверх РАЗРЕШЕНО даже на открытом клапане:
    offset нужен, чтобы удержать клапан приоткрытым, когда PID расслабится
    у цели (мягкая посадка), иначе клапан захлопывается и комната проседает.

    Симметрично вниз: уставка ниже ``local − travel_margin`` — клапан уже
    полностью закрыт, дальше закрывать некуда. Эко-«перегрев» (комната выше
    эко-цели при горячей батарее) иначе хоронит offset к −6 за ночь и убивает
    утренний прогрев. Выход из насыщения не страдает: при offset +6 уставка
    высокая (не ≤ local−margin), при offset −6 — низкая (не ≥ local+margin).

    ``t_local`` None (нет/битый сенсор) → гвард молчит (консервативно).
    """
    if learn_direction == 0 or t_local is None:
        return False
    try:
        ref = float(ref_setpoint)
        loc = float(t_local)
        m = float(travel_margin)
    except (TypeError, ValueError):
        return False
    if learn_direction > 0:
        if ref < loc + m:
            return False
        # Клапан полностью открыт; блокируем только если тепло НЕ течёт
        if t_room is None:
            return True
        return not trv_heat_flowing(t_room, loc, margin=heat_margin)
    return ref <= loc - m


def heat_delivery_state(
    *,
    valve_open_sec: float | None,
    heat_flowing: bool,
    boosting: bool,
    local_rising: bool,
    since_step_up_sec: float | None,
    absent_after_sec: float = 600.0,
    step_up_grace_sec: float = 900.0,
) -> str:
    """Состояние подачи тепла: ``flowing`` / ``absent`` / ``unknown``.

    Честная диагностика «источник не даёт тепло» (карта улучшений P0):
    недогрев, клапан полностью открыт ≥ ``absent_after_sec`` секунд, а
    local так и не поднялся выше room+margin → вода не греет — котёл или
    циркуляция не тянут (детская 02.11: offset улетал к +6 при мёртвой
    комнате, пользователь видел только «не греется»).

    Гварды анти-ложных (батл №2): boost активен → ``unknown``; рост local
    → ``unknown`` (батарея разгоняется); первые ``step_up_grace_sec``
    после скачка цели вверх → ``unknown`` (утренний старт чугуна небыстрый).
    """
    if heat_flowing:
        return "flowing"
    if boosting:
        return "unknown"
    if local_rising:
        return "unknown"
    try:
        grace = float(step_up_grace_sec)
        if since_step_up_sec is not None and float(since_step_up_sec) < grace:
            return "unknown"
        opened = None if valve_open_sec is None else float(valve_open_sec)
        thr = float(absent_after_sec)
    except (TypeError, ValueError):
        return "unknown"
    if opened is not None and opened >= thr:
        return "absent"
    return "unknown"


def should_cold_start_jerk(
    error: float,
    *,
    cold_error: float = 2.0,
    t_room: float | None = None,
    t_local: float | None = None,
    heat_margin: float = 1.5,
    at_trv_max: bool = False,
) -> bool:
    """Нужен ли рывок: большой недогрев и батарея ещё не горячая."""
    try:
        e = float(error)
    except (TypeError, ValueError):
        return False
    if e < float(cold_error):
        return False
    # Уставка уже на максимуме — повторный рывок комнату не греет
    # (гостиная 07.11: TRV 30 и local −0.01, рывок каждые 30 мин).
    if at_trv_max:
        return False
    # Уже течёт тепло — достаточно обычного active + underheat floor
    if t_room is not None and trv_heat_flowing(t_room, t_local, margin=heat_margin):
        return False
    return True


def schedule_target_step(
    prev: float | None,
    cur: float,
    *,
    threshold: float = 2.0,
) -> str | None:
    """Направление скачка сырой цели расписания/пресета.

    Только ``t_target`` (room_target), не ``t_effective``: эко/погода
    дают ложные ±3°C и раньше триггерили boost + сброс learn_freeze.

    Returns:
        ``\"up\"``, ``\"down\"`` или ``None`` (нет скачка / нет prev).
    """
    if prev is None:
        return None
    try:
        delta = float(cur) - float(prev)
        thr = float(threshold)
    except (TypeError, ValueError):
        return None
    if abs(delta) < thr - 1e-9:
        return None
    return "up" if delta > 0 else "down"


def should_arrival_warmup(
    *,
    present: bool,
    prev_present: bool | None,
    boost_active: bool,
    error: float,
    deadband: float,
    now_mono: float,
    last_arrival_boost_mono: float | None,
    cooldown_sec: float,
) -> bool:
    """Нужен ли boost при приходе (после логирования arrival в storage).

    Антиспам: motion как presence мигает → без кулдауна offset у +6.
    Уже у цели / перегрев — греть незачем.
    """
    if prev_present is None:
        return False
    if not (present and not prev_present):
        return False
    if boost_active:
        return False
    try:
        e = float(error)
        db = float(deadband)
        cool = float(cooldown_sec)
    except (TypeError, ValueError):
        return False
    if e <= db:
        return False
    if last_arrival_boost_mono is not None and cool > 0:
        if (float(now_mono) - float(last_arrival_boost_mono)) < cool:
            return False
    return True


def offset_deadband_trim_adjustment(
    offset: float,
    error: float,
    learn_rate_slow: float,
    *,
    soft_trigger: float = _OFFSET_TRIM_SOFT_TRIGGER,
    saturated_trigger: float = _OFFSET_SATURATED_TRIGGER,
    trim_max: float = _OFFSET_TRIM_MAX,
) -> float:
    """Поправка offset в deadband при  soft < |offset| ≤ saturated.

    Выше saturated работает aggressive decay. Ниже soft — не трогаем
    (равновесный offset). Знак: лишний +offset при e≲0 → уменьшаем;
    лишний −offset при e≳0 → увеличиваем.
    """
    try:
        off = float(offset)
        e = float(error)
        rate = float(learn_rate_slow)
    except (TypeError, ValueError):
        return 0.0
    if rate <= 0:
        return 0.0
    # saturated зона — не двойной удар с aggressive decay
    if abs(off) > float(saturated_trigger):
        return 0.0
    if off > float(soft_trigger) and e <= 0.1:
        return -rate * min(float(trim_max), off * 0.1)
    if off < -float(soft_trigger) and e >= -0.1:
        return rate * min(float(trim_max), abs(off) * 0.1)
    return 0.0


def thermostat_device_label(
    climate_entity: str | None,
    climate_friendly_name: str | None = None,
) -> str:
    """Имя устройства ST — не путать с MQTT TRV (Радиатор [Спальня])."""
    if climate_friendly_name:
        return f"Умный термостат · {climate_friendly_name}"
    if climate_entity:
        slug = str(climate_entity).split(".")[-1].replace("_", " ")
        return f"Умный термостат · {slug}"
    return "Умный термостат"


def normalize_entity_list(value: Any) -> list[str]:
    """Нормализовать значение селектора/конфига в список entity_id."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            if v is None:
                continue
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and "entity_id" in v:
                out.append(v["entity_id"])
        return [x for x in out if x]
    return []


def is_truthy_state(state: Any) -> bool:
    """Считать состояние истинным (on/open/true/1)."""
    if state is None:
        return False
    return str(state).lower() in ("on", "open", "true", "1")


def saturated_offset_step(
    offset: float,
    error: float,
    deadband: float,
    *,
    saturated_trigger: float = _OFFSET_SATURATED_TRIGGER,
    underheat_margin: float = _UNDERHEAT_TRV_MARGIN,
    max_step: float = 0.3,
) -> float | None:
    """Куда сдвинуть насыщенный offset за один тик, либо None.

    Плюс у потолка снимаем только до равновесия пола недогрева
    (room+margin−target = margin−error). Ниже этого шага нет:
    уставка TRV не должна упасть под пол, пока цель выше комнаты.

    Минус у потолка поднимаем к нулю только если комната не горячее
    цели. При перегреве отрицательный offset не трогаем — он как раз
    держит клапан тише.
    Вне deadband не учим этим путём.
    """
    try:
        off = float(offset)
        e = float(error)
        db = float(deadband)
        trig = float(saturated_trigger)
        margin = float(underheat_margin)
        step = abs(float(max_step))
    except (TypeError, ValueError):
        return None
    if step <= 0 or db < 0 or abs(e) > db + 1e-9:
        return None
    if off > trig:
        # e>0: не ниже пола. e<=0: можно к нулю, комната уже не холодная.
        floor_off = margin - e if e > 0 else 0.0
        if off <= floor_off + 1e-9:
            return None
        return max(floor_off, off - step)
    if off < -trig and e >= -1e-9:
        return min(0.0, off + step)
    return None


def window_regime_offset(
    live: float,
    parked: float | None,
    *,
    lo: float = -6.0,
    hi: float = 6.0,
) -> tuple[float, float]:
    """Смена режима окна: (смещение режима, в который входим, что припарковать).

    Окна в этом доме открыты большую часть времени. Открытый и закрытый
    режим учатся отдельно: распахнутое окно не утаскивает закрытое смещение
    к +6, закрытие не оставляет уставку, выученную на улицу.

    parked=None — в этот режим ещё не входили, живое смещение не прыгает.
    """
    try:
        live_c = clamp(float(live), lo, hi)
    except (TypeError, ValueError):
        live_c = clamp(0.0, lo, hi)
    if parked is None:
        return live_c, live_c
    try:
        parked_c = clamp(float(parked), lo, hi)
    except (TypeError, ValueError):
        return live_c, live_c
    return parked_c, live_c


def window_control_target(
    t_effective: float,
    eco_temp: float,
    window_open: bool,
) -> float:
    """Пока окно открыто, не гнать комфорт в улицу: цель не выше эко.

    Расписание уже ниже эко (ночь) — не поднимать. Пресет в HA не трогаем:
    автоматизация уставки его перетирает.
    """
    try:
        cur = float(t_effective)
        eco = float(eco_temp)
    except (TypeError, ValueError):
        return t_effective
    if not window_open:
        return cur
    return min(cur, eco)


def commit_debounced_bool(
    raw: bool,
    committed: bool,
    pending_since: float | None,
    now: float,
    debounce_sec: float,
) -> tuple[bool, float | None]:
    """Зафиксировать bool только после стабильного raw.

    Возвращает (committed, pending_since). pending_since — момент, когда
    raw впервые разошёлся с committed; None, если они совпадают.
    """
    try:
        raw_b = bool(raw)
        committed_b = bool(committed)
        now_f = float(now)
        wait = float(debounce_sec)
    except (TypeError, ValueError):
        return bool(committed), pending_since
    if raw_b == committed_b:
        return committed_b, None
    if pending_since is None:
        return committed_b, now_f
    try:
        since = float(pending_since)
    except (TypeError, ValueError):
        return committed_b, now_f
    if now_f - since >= wait - 1e-9:
        return raw_b, None
    return committed_b, since

