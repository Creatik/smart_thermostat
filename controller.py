from __future__ import annotations

import logging
from datetime import timedelta, datetime
from typing import Optional, Dict, Any, Tuple

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import *


STABLE_LEARN_SECONDS = 900  # 15 minutes within deadband
STABLE_LEARN_ALPHA = 0.25   # move offset 25% towards implied value per stable window
MIN_OFFSET_CHANGE = 0.2     # hysteresis for offset updates
MAX_STUCK_BIAS = 4.0        # upper limit for stuck_bias accumulation
OFFSET_DECAY_RATE = 0.01    # 1% decay per day
OFFSET_DECAY_THRESHOLD = 0.1  # минимальный offset для начала decay
OFFSET_LEARN_THRESHOLD = 0.5  # порог для stable learning


LOGGER = logging.getLogger(__name__)


def _clamp(v: float, lo: float, hi: float) -> float:
    """Ограничение значения в диапазоне."""
    return max(lo, min(hi, v))


def _round_step(v: float, step: float) -> float:
    """Округление до шага."""
    if step <= 0:
        return v
    return round(v / step) * step


def _to_float(value: Any) -> Optional[float]:
    """Безопасное преобразование в float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_entity_list(value: Any) -> list[str]:
    """Normalize selector values to a list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if v is None:
                continue
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and "entity_id" in v:
                out.append(v["entity_id"])
        return [x for x in out if x]
    return []


class SmartOffsetController:
    def __init__(self, hass, entry, storage):
        self.hass = hass
        self.entry = entry
        self.storage = storage
        self.unsub = None
        self.last_set: Optional[float] = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error: Optional[float] = None
        self.last_target_trv: Optional[float] = None
        self.change_count = 0
        self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0
        self.window_is_open = False
        self._window_open_since: Optional[float] = None  # for no-learn on long open
        self._last_room_target: Optional[float] = None
        self._unsub_window = None
        self._window_entities: Tuple[str, ...] = tuple()
        self._force_next_control = False
        self._stuck_active = False
        self._stuck_ref_temp: Optional[float] = None
        self._stuck_ref_time: Optional[float] = None
        self._stuck_bias = 0.0
        self._stable_since: Optional[float] = None
        self._stable_target: Optional[float] = None
        self._stable_last_set: Optional[float] = None
        self._history_data: list[Dict[str, Any]] = []  # list of dicts
        self._heating_rate = 0.1
        self._overshoot_count = 0
        self._prev_room_temp: Optional[float] = None
        self._prev_time: Optional[float] = None
        self._learn_rate_slow = 0.1
        self._last_offset_update = 0.0  # для отслеживания времени последнего обновления offset

        # Чтобы не писать heating_rate "по модулю времени" (может дергаться),
        # используем явный таймер последнего сохранения.
        self._last_heating_rate_save: float = 0.0

        self._heat_episode: Optional[Dict[str, float]] = None
        self._minutes_per_degree = (
            self.storage.get_minutes_per_degree(self.entry.entry_id)
            if hasattr(self.storage, "get_minutes_per_degree")
            else 15.0
        )
        self._ttt_alpha = float(self.opt(CONF_TTT_ALPHA) or 0.2)  # EMA

    def opt(self, key: str) -> Any:
        """Получить значение опции с fallback на дефолты."""
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return DEFAULTS.get(key)

    def _notify(self):
        """Уведомить сенсоры об обновлении."""
        now = self.hass.loop.time()
        offset = self.storage.get_offset(self.entry.entry_id)

        # Добавляем запись в историю
        self._history_data.append(
            {
                "time": now,
                "error": self.last_error,
                "offset": offset,
                "trv_set": self.last_set,
                "action": self.last_action,
            }
        )

        # Обрезаем историю (последние 576 записей ~ 48 часов при 5-минутном интервале)
        if len(self._history_data) > 576:
            self._history_data = self._history_data[-576:]

        # Периодически сохраняем историю (каждые 10 записей)
        if len(self._history_data) % 10 == 0:
            self.hass.async_create_task(
                self.storage.set_history(self.entry.entry_id, self._history_data)
            )

        # Отправляем сигнал обновления
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    def _maybe_start_heat_episode(
        self, now_mono: float, t_room: float, t_target: float, deadband: float
    ):
        e = t_target - t_room
        if e <= deadband:
            return
        if self.window_is_open or self.boost_active:
            return
        if self._heat_episode is not None:
            return

        self._heat_episode = {
            "t0": now_mono,
            "room0": t_room,
            "target0": t_target,
            "e0": e,
            "max_room": t_room,
        }

    def _update_heat_episode(self, t_room: float):
        if self._heat_episode is None:
            return
        self._heat_episode["max_room"] = max(self._heat_episode["max_room"], t_room)

    async def _maybe_finish_heat_episode(
        self, now_mono: float, t_room: float, t_target: float, deadband: float
    ):
        if self._heat_episode is None:
            return

        # финиш: достигли цели (или вошли в deadband сверху/снизу — на твой вкус)
        if t_room + deadband < t_target:
            return

        t0 = self._heat_episode["t0"]
        e0 = max(0.1, self._heat_episode["e0"])  # защита от деления
        minutes = (now_mono - t0) / 60.0
        mpd = minutes / e0  # minutes per degree

        # ограничим мусор (например, если кто-то открыл окно и т.п.)
        mpd = _clamp(mpd, 2.0, 120.0)

        self._minutes_per_degree = (
            self._ttt_alpha * mpd + (1 - self._ttt_alpha) * self._minutes_per_degree
        )

        # при желании — сохраняем
        if hasattr(self.storage, "set_minutes_per_degree"):
            await self.storage.set_minutes_per_degree(
                self.entry.entry_id, self._minutes_per_degree
            )

        LOGGER.info(
            "TTT learn: minutes=%.1f e0=%.2f => mpd=%.1f, ema_mpd=%.1f",
            minutes,
            e0,
            mpd,
            self._minutes_per_degree,
        )

        self._heat_episode = None

    def _ensure_window_listener(self, window_entities: Optional[list[str]]):
        """Настроить отслеживание состояния окон."""
        entities = tuple([e for e in _normalize_entity_list(window_entities) if e])

        if entities == self._window_entities:
            return

        # Отписываемся от старого слушателя
        if self._unsub_window:
            try:
                self._unsub_window()
            except Exception:
                pass
            self._unsub_window = None

        self._window_entities = entities

        if not entities:
            return

        def _compute_open() -> bool:
            """Вычислить, открыто ли хоть одно окно."""
            for ent in entities:
                st = self.hass.states.get(ent)
                if st is None:
                    continue
                if str(st.state).lower() in ("on", "open", "true", "1"):
                    return True
            return False

        async def _on_window_change(event):
            """Обработчик изменения состояния окна."""
            is_open = _compute_open()
            now = self.hass.loop.time()

            if is_open != self.window_is_open:
                self.window_is_open = is_open
                if is_open:
                    self._window_open_since = now
                else:
                    self._window_open_since = None

            await self.trigger_once(force=True)
            self._notify()

        self._unsub_window = async_track_state_change_event(
            self.hass, list(entities), _on_window_change
        )

    def _cancel_boost(self):
        """Отменить режим boost."""
        if self._boost_unsub:
            try:
                self._boost_unsub()
            except Exception:
                pass
            self._boost_unsub = None

        self.boost_active = False
        self.boost_until = 0.0

    async def reset_offset(self):
        """Сбросить offset к нулю."""
        await self.storage.set_offset(self.entry.entry_id, 0.0, reason="manual_reset")
        self.last_action = "reset_offset"
        await self.trigger_once(force=True)
        self._notify()

    async def start_boost(self):
        """Запустить режим boost."""
        duration = int(
            self.opt(CONF_BOOST_DURATION_SEC) or DEFAULT_BOOST_DURATION_SEC
        )
        duration = max(30, min(duration, 3600))

        self._cancel_boost()
        self.boost_active = True
        self.boost_until = self.hass.loop.time() + float(duration)

        async def _end(_):
            """Завершение режима boost."""
            self._cancel_boost()
            await self.trigger_once(force=True)
            self._notify()

        self._boost_unsub = async_call_later(self.hass, float(duration), _end)
        await self.trigger_once(force=True)
        self._notify()

    async def async_start(self):
        """Запуск контроллера."""
        # Загружаем историю из storage (get_history синхронный)
        self._history_data = self.storage.get_history(self.entry.entry_id) or []

        # Загружаем heating rate и overshoot count
        self._heating_rate = self.storage.get_heating_rate(self.entry.entry_id)
        self._overshoot_count = self.storage.get_overshoot_count(self.entry.entry_id)
        self._learn_rate_slow = float(
            self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW
        )

        # Настраиваем периодический вызов
        interval = int(self.opt(CONF_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC)
        self.unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=interval)
        )

        # Первый запуск
        await self._tick(None)

    async def async_stop(self):
        """Остановка контроллера."""
        self._cancel_boost()

        if self.unsub:
            self.unsub()
            self.unsub = None

        # Сохраняем heating rate и overshoot count
        await self.storage.set_heating_rate(
            self.entry.entry_id, self._heating_rate, reason="shutdown"
        )
        await self.storage.set_overshoot_count(
            self.entry.entry_id, self._overshoot_count
        )

        # Сохраняем историю
        await self.storage.set_history(self.entry.entry_id, self._history_data)

    async def trigger_once(self, force: bool = False):
        """Запустить один цикл управления."""
        if force:
            self._force_next_control = True
        await self._tick(None)

    def _reset_stability_tracking(self):
        """Сбросить отслеживание стабильности."""
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None

    async def _set_trv_temperature(self, entity_id: str, temp: float) -> bool:
        """Установить температуру на термостате."""
        now = self.hass.loop.time()

        # Проверяем, нужно ли менять температуру
        if self.last_set is not None and abs(temp - self.last_set) < 0.01:
            return False

        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, ATTR_TEMPERATURE: temp},
                blocking=False,
            )

            self.last_set = temp
            self.last_change = now
            self.change_count += 1
            self._force_next_control = False

            LOGGER.debug("Установлена температура %.2f°C на %s", temp, entity_id)
            return True

        except Exception as e:
            LOGGER.error("Ошибка установки температуры на %s: %s", entity_id, str(e))
            self.last_action = "set_failed"
            return False

    async def _get_sensor_data(self) -> Optional[Dict[str, Any]]:
        """Получить данные с датчиков."""
        climate_entity = self.entry.data[CONF_CLIMATE]
        room_sensor = self.entry.data[CONF_ROOM_SENSOR]

        climate = self.hass.states.get(climate_entity)
        room = self.hass.states.get(room_sensor)

        if not climate or not room:
            self.last_action = "skipped_unavailable_entities"
            return None

        t_room = _to_float(room.state)
        if t_room is None:
            self.last_action = "skipped_invalid_room_temp"
            return None

        t_target = float(self.opt(CONF_ROOM_TARGET) or DEFAULTS[CONF_ROOM_TARGET])

        return {
            "climate_entity": climate_entity,
            "room_sensor": room_sensor,
            "t_room": t_room,
            "t_target": t_target,
            "climate_state": climate,
        }

    async def _handle_window_condition(self, data: Dict[str, Any]) -> bool:
        """Обработка условия открытого окна."""
        window_entities = _normalize_entity_list(self.opt(CONF_WINDOW_SENSORS))
        old_window = self.opt(CONF_WINDOW_SENSOR)

        if old_window and old_window not in window_entities:
            window_entities = list(window_entities) + [old_window]

        self._ensure_window_listener(list(window_entities))

        # Проверяем состояние окон
        window_open = False
        for _we in window_entities:
            w_state = self.hass.states.get(_we)
            if not w_state:
                continue
            if str(w_state.state).lower() in ("on", "open", "true", "1"):
                window_open = True
                break

        if window_open != self.window_is_open:
            self.window_is_open = window_open

        if not window_open:
            return False

        # Окно открыто - устанавливаем минимальную температуру
        self._cancel_boost()
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        t_trv = trv_min
        self.last_target_trv = t_trv

        if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
            await self._set_trv_temperature(data["climate_entity"], t_trv)

        self.last_action = "window_open"
        self._stuck_bias = 0.0
        return True

    async def _handle_boost_condition(self, data: Dict[str, Any]) -> bool:
        """Обработка условия boost."""
        if not self.boost_active or self.hass.loop.time() >= self.boost_until:
            return False

        # Boost активен - устанавливаем максимальную температуру
        self._reset_stability_tracking()
        self._stuck_bias = 0.0

        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        t_trv = _clamp(trv_max, trv_min, trv_max)
        self.last_target_trv = t_trv

        if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
            await self._set_trv_temperature(data["climate_entity"], t_trv)

        self.last_action = "boost"
        return True

    async def _handle_deadband(self, data: Dict[str, Any], deadband: float) -> bool:
        """Обработка deadband режима."""
        t_room = data["t_room"]
        t_target = data["t_target"]
        e = t_target - t_room

        if abs(e) > deadband:
            return False

        # В deadband - поддерживаем текущую температуру или baseline
        offset = self.storage.get_offset(self.entry.entry_id)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        baseline = t_target + offset
        baseline = _clamp(baseline, trv_min, trv_max)
        baseline = _round_step(baseline, step_min)

        # Проверяем, изменилась ли целевая температура
        target_changed = (
            self._last_room_target is not None
            and abs(t_target - self._last_room_target) > 1e-9
        )
        self._last_room_target = t_target

        if target_changed or self.last_set is None:
            self.last_target_trv = baseline
            if self.last_set is None or abs(baseline - self.last_set) >= (
                step_min - 1e-9
            ):
                await self._set_trv_temperature(data["climate_entity"], baseline)
                self.last_action = (
                    "deadband_rebase" if target_changed else "deadband_init"
                )
            self._reset_stability_tracking()
            return True

        self.last_target_trv = self.last_set
        self.last_action = "hold"

        # Стабильное обучение в deadband
        await self._handle_stable_learning(data, deadband)
        return True

    async def _handle_stable_learning(self, data: Dict[str, Any], deadband: float):
        """Обработка стабильного обучения в deadband."""
        t_room = data["t_room"]
        t_target = data["t_target"]

        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))
        no_learn_summer = bool(
            self.opt(CONF_NO_LEARN_SUMMER) or DEFAULT_NO_LEARN_SUMMER
        )
        window_no_learn_min = int(
            self.opt(CONF_WINDOW_OPEN_NO_LEARN_MIN)
            or DEFAULT_WINDOW_OPEN_NO_LEARN_MIN
        )

        now_mono = self.hass.loop.time()
        now_dt = datetime.now()

        # Проверяем условия no-learn
        is_summer = no_learn_summer and 6 <= now_dt.month <= 8
        long_window_open = (
            self.window_is_open
            and self._window_open_since is not None
            and (now_mono - self._window_open_since >= window_no_learn_min * 60)
        )
        no_learn = is_summer or long_window_open

        if not enable_learning or no_learn or self.last_set is None:
            return

        # Инициализируем или обновляем отслеживание стабильности
        if self._stable_since is None or self._stable_target != t_target:
            self._stable_since = now_mono
            self._stable_target = t_target
            self._stable_last_set = self.last_set

        # Проверяем, достаточно ли времени в стабильном состоянии
        elif now_mono - self._stable_since >= STABLE_LEARN_SECONDS:
            # Вычисляем implied_offset на основе фактической температуры комнаты
            implied_offset = self.last_set - t_room
            implied_offset = _clamp(implied_offset, MIN_OFFSET, MAX_OFFSET)

            current_offset = self.storage.get_offset(self.entry.entry_id)
            min_offset_change = float(
                self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
            )

            # Обучаемся только если разница значительна
            if abs(implied_offset - current_offset) > OFFSET_LEARN_THRESHOLD:
                new_offset = current_offset + STABLE_LEARN_ALPHA * (
                    implied_offset - current_offset
                )

                if abs(new_offset - current_offset) >= min_offset_change:
                    await self.storage.set_offset(
                        self.entry.entry_id, new_offset, reason="stable_learn"
                    )
                    self.last_action = "stable_learn"
                    self._last_offset_update = now_mono

                    LOGGER.debug(
                        "Stable learning: room=%.2f target=%.2f last_set=%.2f implied=%.2f current=%.2f new=%.2f",
                        t_room,
                        t_target,
                        self.last_set,
                        implied_offset,
                        current_offset,
                        new_offset,
                    )

            self._stuck_bias = 0.0
            self._reset_stability_tracking()

    async def _handle_active_control(self, data: Dict[str, Any]):
        """Обработка активного управления вне deadband."""
        t_room = data["t_room"]
        t_target = data["t_target"]
        e = t_target - t_room

        # Получаем параметры
        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        step_max = float(self.opt(CONF_STEP_MAX) or DEFAULT_STEP_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        learn_rate_fast = float(self.opt(CONF_LEARN_RATE_FAST) or DEFAULT_LEARN_RATE_FAST)
        min_offset_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        cooldown = float(self.opt(CONF_COOLDOWN_SEC) or DEFAULT_COOLDOWN_SEC)
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))

        # Параметры для overshoot prevention
        heating_alpha = float(self.opt(CONF_HEATING_ALPHA) or 0.1)
        overshoot_threshold = float(self.opt(CONF_OVERSHOOT_THRESHOLD) or 0.5)
        predict_minutes = int(self.opt(CONF_PREDICT_MINUTES) or 5)

        # Stuck detection параметры
        stuck_enable = bool(self.opt(CONF_STUCK_ENABLE))
        stuck_seconds = int(self.opt(CONF_STUCK_SECONDS) or DEFAULT_STUCK_SECONDS)
        stuck_min_drop = float(self.opt(CONF_STUCK_MIN_DROP) or DEFAULT_STUCK_MIN_DROP)
        stuck_step = float(self.opt(CONF_STUCK_STEP) or DEFAULT_STUCK_STEP)

        now_mono = self.hass.loop.time()

        self._maybe_start_heat_episode(now_mono, t_room, t_target, deadband)
        self._update_heat_episode(t_room)
        await self._maybe_finish_heat_episode(now_mono, t_room, t_target, deadband)

        # Получаем текущий offset
        offset = self.storage.get_offset(self.entry.entry_id)

        # Детект overshoot
        if t_room > t_target + overshoot_threshold:
            new_count = await self.storage.increment_overshoot_count(self.entry.entry_id)
            self._overshoot_count = new_count

            if self._overshoot_count > 3:
                self._learn_rate_slow = max(0.01, self._learn_rate_slow * 0.9)
                LOGGER.info(
                    "Auto-tune: снижен learn_rate_slow до %.3f из-за перегрева",
                    self._learn_rate_slow,
                )
                self._overshoot_count = 0

        # Активное обучение
        learn_rate = learn_rate_fast if abs(e) > deadband * 2 else self._learn_rate_slow

        if enable_learning and abs(e) > deadband:
            # Определяем направление обучения
            learn_direction = 1 if e > 0 else -1
            new_offset = _clamp(
                offset + learn_direction * learn_rate * abs(e), MIN_OFFSET, MAX_OFFSET
            )
            old_offset = offset
            if abs(new_offset - offset) >= min_offset_change:
                offset = new_offset

                await self.storage.set_offset(
                    self.entry.entry_id, offset, reason="active_learning"
                )
                self._last_offset_update = now_mono

                LOGGER.debug(
                    "Active learning: error=%.2f direction=%d rate=%.3f offset=%.2f -> %.2f",
                    e,
                    learn_direction,
                    learn_rate,
                    old_offset,
                    offset,
                )

        # Вычисляем коррекцию
        correction = _clamp(0.5 * e, -step_max, step_max)

        if e > 0:
            predicted_minutes_ttt = e * self._minutes_per_degree

            # например: если < 10 минут до цели — начинаем отпускать
            ttt_soft_min = float(self.opt(CONF_TTT_SOFT_MIN) or 10.0)
            if predicted_minutes_ttt < ttt_soft_min:
                factor = _clamp(predicted_minutes_ttt / ttt_soft_min, 0.3, 1.0)
                correction *= factor
                LOGGER.debug(
                    "TTT soft-landing: predicted=%.1f min, factor=%.2f",
                    predicted_minutes_ttt,
                    factor,
                )

        # Предсказание и предотвращение overshoot
        if e > 0 and self._heating_rate > 0.001:
            predicted_time = e / self._heating_rate
            if predicted_time < predict_minutes:
                factor = max(
                    0.5, 1 - (predict_minutes - predicted_time) / predict_minutes
                )
                correction *= factor
                LOGGER.debug(
                    "Overshoot prevention: predicted_time=%.1f min, correction factor=%.2f",
                    predicted_time,
                    factor,
                )

        # Вычисляем целевую температуру TRV
        t_trv = _round_step(t_target + offset + correction, step_min)

        # Stuck bias (overtemp detection)
        if stuck_enable and not self.window_is_open and not self.boost_active:
            t_trv = await self._handle_stuck_detection(
                t_room,
                e,
                deadband,
                stuck_seconds,
                stuck_min_drop,
                stuck_step,
                now_mono,
                t_trv,
                step_min,
                trv_min,
                trv_max,
            )

        if e < -deadband and self._stuck_bias > 0:
            t_trv = _round_step(_clamp(t_trv - self._stuck_bias, trv_min, trv_max), step_min)

        t_trv = _clamp(t_trv, trv_min, trv_max)
        self.last_target_trv = t_trv

        # Проверка cooldown и необходимости изменения
        if self.last_set is not None:
            if abs(t_trv - self.last_set) < (step_min - 1e-9):
                self.last_action = "skipped_no_change"
                return

            if (now_mono - self.last_change) < cooldown and not self._force_next_control:
                self.last_action = "cooldown"
                return

        # Применение новой уставки
        success = await self._set_trv_temperature(data["climate_entity"], t_trv)
        if success:
            self.last_action = "set_temperature"

            LOGGER.debug(
                "set_temperature: entity=%s room=%.2f target=%.2f error=%.2f offset=%.2f correction=%.2f trv=%.2f rate=%.3f",
                data["climate_entity"],
                t_room,
                t_target,
                e,
                offset,
                correction,
                t_trv,
                self._heating_rate,
            )

        # Обновление heating rate (только если нагреваем)
        if e > deadband and not self.window_is_open and not self.boost_active:
            await self._update_heating_rate(t_room, now_mono, heating_alpha)

        # Автоматическое уменьшение offset со временем (decay)
        await self._handle_offset_decay(now_mono, enable_learning)

    async def _handle_stuck_detection(
        self,
        t_room: float,
        e: float,
        deadband: float,
        stuck_seconds: int,
        stuck_min_drop: float,
        stuck_step: float,
        now_mono: float,
        t_trv: float,
        step_min: float,
        trv_min: float,
        trv_max: float,
    ):
        """Обработка детектирования залипания (перегрев)."""
        if e < -deadband:
            if not self._stuck_active:
                self._stuck_active = True
                self._stuck_ref_temp = t_room
                self._stuck_ref_time = now_mono
            else:
                if self._stuck_ref_time and (now_mono - self._stuck_ref_time >= stuck_seconds):
                    ref_temp = self._stuck_ref_temp if self._stuck_ref_temp is not None else t_room
                    if t_room >= (ref_temp - stuck_min_drop):
                        self._stuck_bias = min(self._stuck_bias + stuck_step, MAX_STUCK_BIAS)
                        t_trv = _round_step(_clamp(t_trv - stuck_step, trv_min, trv_max), step_min)
                        self.last_action = "stuck_overtemp_down"
                    self._stuck_ref_temp = t_room
                    self._stuck_ref_time = now_mono
        else:
            self._stuck_active = False
            self._stuck_ref_temp = None
            self._stuck_ref_time = None
            self._stuck_bias = 0.0

        return t_trv

    async def _update_heating_rate(self, t_room: float, now_mono: float, heating_alpha: float):
        """Обновить скорость нагрева (°C/мин).

        Важно: prev_* обновляются в _tick() на каждом тике, чтобы dt не “раздувался”
        после window_open/boost/deadband.
        """
        if self._prev_room_temp is None or self._prev_time is None:
            return

        dt_min = (now_mono - self._prev_time) / 60.0
        # Защита от мусора: слишком маленький/большой шаг времени даст плохую скорость.
        if dt_min <= 0:
            return
        if dt_min < 0.25:   # < 15 секунд
            return
        if dt_min > 30.0:   # > 30 минут
            return

        dT = t_room - self._prev_room_temp
        if dT <= 0:
            return  # только подъём температуры

        current_rate = dT / dt_min
        self._heating_rate = heating_alpha * current_rate + (1 - heating_alpha) * self._heating_rate

        # Сохраняем не чаще, чем раз в 5 минут (и только если значение "живое")
        if (now_mono - self._last_heating_rate_save) >= 300:
            self._last_heating_rate_save = now_mono
            await self.storage.set_heating_rate(
                self.entry.entry_id, self._heating_rate, reason="auto_update"
            )

    async def _handle_offset_decay(self, now_mono: float, enable_learning: bool):
        """Обработка decay offset со временем."""
        if not enable_learning or self._last_offset_update <= 0:
            return

        days_since_update = (now_mono - self._last_offset_update) / (24 * 3600)
        if days_since_update > 1:  # Прошло более суток
            current_offset = self.storage.get_offset(self.entry.entry_id)
            min_offset_change = float(
                self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
            )

            if abs(current_offset) > OFFSET_DECAY_THRESHOLD:
                decay = OFFSET_DECAY_RATE * days_since_update
                mult = max(0.0, 1.0 - decay)
                new_offset = current_offset * mult

                if abs(new_offset - current_offset) >= min_offset_change:
                    await self.storage.set_offset(
                        self.entry.entry_id, new_offset, reason="offset_decay"
                    )
                    self._last_offset_update = now_mono

                    LOGGER.info(
                        "Offset decay: days=%.1f decay=%.3f offset=%.2f -> %.2f",
                        days_since_update,
                        decay,
                        current_offset,
                        new_offset,
                    )

    async def _tick(self, _):
        """Основной цикл управления."""
        now_mono = self.hass.loop.time()

        # Получаем данные с датчиков
        data = await self._get_sensor_data()
        if not data:
            self._notify()
            return

        t_room = data["t_room"]
        t_target = data["t_target"]
        e = t_target - t_room
        self.last_error = round(e, 3)

        # Проверяем приоритетные условия
        if await self._handle_window_condition(data):
            # Важно: обновляем prev_* даже если управление было "window_open",
            # чтобы dt для heating_rate не стало огромным на следующем активном тике.
            self._prev_room_temp = t_room
            self._prev_time = now_mono
            self._notify()
            return

        if await self._handle_boost_condition(data):
            self._prev_room_temp = t_room
            self._prev_time = now_mono
            self._notify()
            return

        # Проверяем deadband
        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        if await self._handle_deadband(data, deadband):
            self._prev_room_temp = t_room
            self._prev_time = now_mono
            self._notify()
            return

        # Активное управление
        await self._handle_active_control(data)

        # Всегда сохраняем “точку отсчёта” для следующей оценки скорости нагрева.
        self._prev_room_temp = t_room
        self._prev_time = now_mono

        self._notify()
