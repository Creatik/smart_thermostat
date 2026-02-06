from __future__ import annotations
import logging
from datetime import timedelta, datetime
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.event import async_track_time_interval, async_call_later, async_track_state_change_event
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import *

STABLE_LEARN_SECONDS = 900  # 15 minutes within deadband
STABLE_LEARN_ALPHA = 0.25  # move offset 25% towards implied value per stable window
MIN_OFFSET_CHANGE = 0.2  # hysteresis for offset updates
MAX_STUCK_BIAS = 4.0  # upper limit for stuck_bias accumulation
OFFSET_DECAY_RATE = 0.01  # 1% decay per day
OFFSET_DECAY_THRESHOLD = 0.1  # минимальный offset для начала decay
OFFSET_LEARN_THRESHOLD = 0.5  # порог для stable learning

LOGGER = logging.getLogger(__name__)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _round_step(v, step):
    if step <= 0:
        return v
    return round(v / step) * step


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _normalize_entity_list(value):
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
            elif isinstance(v, dict) and 'entity_id' in v:
                out.append(v['entity_id'])
        return [x for x in out if x]
    return []


class SmartOffsetController:
    def __init__(self, hass, entry, storage):
        self.hass = hass
        self.entry = entry
        self.storage = storage
        self.unsub = None
        self.last_set = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error = None
        self.last_target_trv = None
        self.change_count = 0
        self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0
        self.window_is_open = False
        self._window_open_since = None  # for no-learn on long open
        self._last_room_target = None
        self._unsub_window = None
        self._window_entities = tuple()
        self._force_next_control = False
        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None
        self._history_data = []  # list of dicts: {'time': float, 'error': float, 'offset': float, 'trv_set': float}
        self._heating_rate = self.storage.get_heating_rate(self.entry.entry_id) or 0.1
        self._overshoot_count = self.storage.get_overshoot_count(self.entry.entry_id) or 0
        self._prev_room_temp = None
        self._prev_time = None
        self._learn_rate_slow = float(self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW)
        self._last_offset_update = 0.0  # для отслеживания времени последнего обновления offset

    def opt(self, key):
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return DEFAULTS.get(key)

    def _notify(self):
        # Update history (keep last 48 hours, ~1 point per 5 min → ~576 points)
        now = self.hass.loop.time()
        offset = self.storage.get_offset(self.entry.entry_id)
        self._history_data.append({
            'time': now,
            'error': self.last_error,
            'offset': offset,
            'trv_set': self.last_set
        })
        # Prune old data
        cutoff = now - 48 * 3600
        self._history_data = [p for p in self._history_data if p['time'] >= cutoff]
        # Save to storage periodically (every 10 updates)
        if len(self._history_data) % 10 == 0:
            self.storage.set_history(self.entry.entry_id, self._history_data)
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    def _ensure_window_listener(self, window_entities: list[str] | None):
        entities = tuple([e for e in _normalize_entity_list(window_entities) if e])
        if entities == self._window_entities:
            return
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
            for ent in entities:
                st = self.hass.states.get(ent)
                if st is None:
                    continue
                if str(st.state).lower() in ("on", "open", "true", "1"):
                    return True
            return False

        async def _on_window_change(event):
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

        self._unsub_window = async_track_state_change_event(self.hass, list(entities), _on_window_change)

    def _cancel_boost(self):
        if self._boost_unsub:
            try:
                self._boost_unsub()
            except Exception:
                pass
            self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0

    async def reset_offset(self):
        self.storage.set_offset(self.entry.entry_id, 0.0)
        await self.storage.async_save()
        self.last_action = "reset_offset"
        await self.trigger_once(force=True)
        self._notify()

    async def start_boost(self):
        duration = int(self.opt(CONF_BOOST_DURATION_SEC) or DEFAULT_BOOST_DURATION_SEC)
        duration = max(30, min(duration, 3600))
        self._cancel_boost()
        self.boost_active = True
        self.boost_until = self.hass.loop.time() + float(duration)

        async def _end(_):
            self._cancel_boost()
            await self.trigger_once(force=True)
            self._notify()

        self._boost_unsub = async_call_later(self.hass, float(duration), _end)
        await self.trigger_once(force=True)
        self._notify()

    async def async_start(self):
        # Load history from storage
        self._history_data = self.storage.get_history(self.entry.entry_id) or []
        interval = int(self.opt(CONF_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC)
        self.unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=interval)
        )
        await self._tick(None)

    async def async_stop(self):
        self._cancel_boost()
        if self.unsub:
            self.unsub()
            self.unsub = None
        # Save history on stop
        self.storage.set_heating_rate(self.entry.entry_id, self._heating_rate)
        self.storage.set_overshoot_count(self.entry.entry_id, self._overshoot_count)
        await self.storage.async_save()

    async def trigger_once(self, force: bool = False):
        if force:
            self._force_next_control = True
        await self._tick(None)

    def _reset_stability_tracking(self):
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None

    async def _set_trv_temperature(self, entity_id: str, temp: float):
        now = self.hass.loop.time()
        if self.last_set is not None and abs(temp - self.last_set) < 0.01:
            return False
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": entity_id, ATTR_TEMPERATURE: temp},
            blocking=False,
        )
        self.last_set = temp
        self.last_change = now
        self.change_count += 1
        self._force_next_control = False
        return True

    async def _tick(self, _):
        climate_entity = self.entry.data[CONF_CLIMATE]
        room_sensor = self.entry.data[CONF_ROOM_SENSOR]
        window_entities = _normalize_entity_list(self.opt(CONF_WINDOW_SENSORS))
        # backward compatible: old single key
        old_window = self.opt(CONF_WINDOW_SENSOR)
        if old_window and old_window not in window_entities:
            window_entities = list(window_entities) + [old_window]
        self._ensure_window_listener(list(window_entities))

        climate = self.hass.states.get(climate_entity)
        room = self.hass.states.get(room_sensor)
        if not climate or not room:
            self.last_action = "skipped_unavailable_entities"
            self._notify()
            return

        t_room = _to_float(room.state)
        if t_room is None:
            self.last_action = "skipped_invalid_room_temp"
            self._notify()
            return

        t_target = float(self.opt(CONF_ROOM_TARGET) or DEFAULTS[CONF_ROOM_TARGET])
        target_changed = (self._last_room_target is not None and abs(t_target - self._last_room_target) > 1e-9)
        self._last_room_target = t_target

        stuck_enable = bool(self.opt(CONF_STUCK_ENABLE))
        stuck_seconds = int(self.opt(CONF_STUCK_SECONDS) or DEFAULT_STUCK_SECONDS)
        stuck_min_drop = float(self.opt(CONF_STUCK_MIN_DROP) or DEFAULT_STUCK_MIN_DROP)
        stuck_step = float(self.opt(CONF_STUCK_STEP) or DEFAULT_STUCK_STEP)
        stuck_seconds = max(300, min(stuck_seconds, 24 * 3600))
        stuck_min_drop = max(0.0, min(stuck_min_drop, 5.0))
        stuck_step = max(0.05, min(stuck_step, 5.0))

        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        step_max = float(self.opt(CONF_STEP_MAX) or DEFAULT_STEP_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        learn_rate_fast = float(self.opt(CONF_LEARN_RATE_FAST) or DEFAULT_LEARN_RATE_FAST)
        learn_rate_slow = float(self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW)
        min_offset_change = float(self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        cooldown = float(self.opt(CONF_COOLDOWN_SEC) or DEFAULT_COOLDOWN_SEC)
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))
        no_learn_summer = bool(self.opt(CONF_NO_LEARN_SUMMER) or DEFAULT_NO_LEARN_SUMMER)
        window_no_learn_min = int(self.opt(CONF_WINDOW_OPEN_NO_LEARN_MIN) or DEFAULT_WINDOW_OPEN_NO_LEARN_MIN)

        # Параметры для предсказания и предотвращения overshoot
        heating_alpha = float(self.opt(CONF_HEATING_ALPHA) or 0.1)
        overshoot_threshold = float(self.opt(CONF_OVERSHOOT_THRESHOLD) or 0.5)
        predict_minutes = int(self.opt(CONF_PREDICT_MINUTES) or 5)

        # Window handling
        window_open = False
        if window_entities:
            for _we in window_entities:
                w_state = self.hass.states.get(_we)
                if not w_state:
                    continue
                if str(w_state.state).lower() in ("on", "open", "true", "1"):
                    window_open = True
                    break

        if window_open != self.window_is_open:
            self.window_is_open = window_open

        e = t_target - t_room
        self.last_error = round(e, 3)

        now_mono = self.hass.loop.time()
        now_dt = datetime.now()

        # reset stability if outside deadband or no-learn conditions
        is_summer = no_learn_summer and 6 <= now_dt.month <= 8
        long_window_open = self.window_is_open and self._window_open_since and (now_mono - self._window_open_since >= window_no_learn_min)
        no_learn = is_summer or long_window_open

        if abs(e) > deadband or no_learn:
            self._reset_stability_tracking()

        # Highest priority: window open → set TRV to minimum and pause learning
        if window_open:
            self._cancel_boost()
            t_trv = _clamp(trv_min, trv_min, trv_max)
            self.last_target_trv = t_trv
            if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
                await self._set_trv_temperature(climate_entity, t_trv)
            self.last_action = "window_open"
            self._stuck_bias = 0.0
            self._notify()
            return

        # Next priority: boost active → set TRV to max for boost duration
        if self.boost_active and (now_mono < self.boost_until):
            self._reset_stability_tracking()
            self._stuck_bias = 0.0
            t_trv = _clamp(trv_max, trv_min, trv_max)
            self.last_target_trv = t_trv
            if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
                await self._set_trv_temperature(climate_entity, t_trv)
            self.last_action = "boost"
            self._notify()
            return

        # Deadband logic
        if abs(e) <= deadband:
            baseline = t_target + self.storage.get_offset(self.entry.entry_id)
            baseline = _clamp(baseline, trv_min, trv_max)
            baseline = _round_step(baseline, step_min)

            if target_changed or self.last_set is None:
                self.last_target_trv = baseline
                if self.last_set is None or abs(baseline - self.last_set) >= (step_min - 1e-9):
                    await self._set_trv_temperature(climate_entity, baseline)
                    self.last_action = "deadband_rebase" if target_changed else "deadband_init"
                self._reset_stability_tracking()
                self._notify()
                return

            self.last_target_trv = self.last_set
            self.last_action = "hold"

            if enable_learning and not no_learn and self.last_set is not None:
                if self._stable_since is None or self._stable_target != t_target:
                    self._stable_since = now_mono
                    self._stable_target = t_target
                    self._stable_last_set = self.last_set
                elif now_mono - self._stable_since >= STABLE_LEARN_SECONDS:
                    # ИСПРАВЛЕНИЕ: вычисляем implied_offset на основе фактической температуры комнаты
                    # а не целевой температуры
                    implied_offset = self.last_set - t_room  # Изменено с t_target на t_room
                    implied_offset = _clamp(implied_offset, -10.0, 10.0)
                    current_offset = self.storage.get_offset(self.entry.entry_id)
                    
                    # Обучаемся только если разница значительна
                    if abs(implied_offset - current_offset) > OFFSET_LEARN_THRESHOLD:
                        new_offset = current_offset + STABLE_LEARN_ALPHA * (implied_offset - current_offset)
                        if abs(new_offset - current_offset) >= min_offset_change:
                            self.storage.set_offset(self.entry.entry_id, new_offset)
                            await self.storage.async_save()
                            self.last_action = "stable_learn"
                            self._last_offset_update = now_mono
                            LOGGER.debug(
                                "Stable learning: room=%.2f target=%.2f last_set=%.2f implied=%.2f current=%.2f new=%.2f",
                                t_room, t_target, self.last_set, implied_offset, current_offset, new_offset
                            )
                    
                    self._stuck_bias = 0.0
                    self._reset_stability_tracking()

            self._notify()
            return

        # Outside deadband: active control + learning + overshoot prevention
        offset = self.storage.get_offset(self.entry.entry_id)

        # Детект overshoot (перед расчётом learn_rate)
        if t_room > t_target + overshoot_threshold:
            self._overshoot_count += 1
            if self._overshoot_count > 3:
                self._learn_rate_slow = max(0.01, self._learn_rate_slow * 0.9)
                LOGGER.info("Auto-tune: снижен learn_rate_slow до %.3f из-за перегрева", self._learn_rate_slow)
                self._overshoot_count = 0

        learn_rate = learn_rate_fast if abs(e) > deadband * 2 else self._learn_rate_slow

        # ИСПРАВЛЕНИЕ: симметричное обучение для нагрева и охлаждения
        if enable_learning and not no_learn and abs(e) > deadband:
            # Определяем направление обучения
            learn_direction = 1 if e > 0 else -1  # положительное для нагрева, отрицательное для охлаждения
            new_offset = _clamp(offset + learn_direction * learn_rate * abs(e), -10.0, 10.0)
            if abs(new_offset - offset) >= min_offset_change:
                offset = new_offset
                self.storage.set_offset(self.entry.entry_id, offset)
                await self.storage.async_save()
                self._last_offset_update = now_mono
                LOGGER.debug(
                    "Active learning: error=%.2f direction=%d rate=%.3f offset=%.2f -> %.2f",
                    e, learn_direction, learn_rate, self.storage.get_offset(self.entry.entry_id), offset
                )

        correction = _clamp(0.5 * e, -step_max, step_max)

        # Предсказание и предотвращение overshoot
        predicted_time = None
        if self._heating_rate > 0.001:  # защита от очень маленьких значений
            predicted_time = e / self._heating_rate
            if predicted_time < predict_minutes:
                factor = max(0.5, 1 - (predict_minutes - predicted_time) / predict_minutes)
                correction *= factor
                LOGGER.debug("Overshoot prevention: predicted_time=%.1f min, correction factor=%.2f", predicted_time, factor)

        t_trv = _round_step(t_target + offset + correction, step_min)

        # Stuck bias (overtemp detection)
        if stuck_enable and not window_open and not self.boost_active:
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

        if e < -deadband and self._stuck_bias > 0:
            t_trv = _round_step(_clamp(t_trv - self._stuck_bias, trv_min, trv_max), step_min)

        t_trv = _clamp(t_trv, trv_min, trv_max)
        self.last_target_trv = t_trv

        # Проверка cooldown и необходимости изменения
        if self.last_set is not None:
            if abs(t_trv - self.last_set) < (step_min - 1e-9):
                self.last_action = "skipped_no_change"
                self._notify()
                return
            if (now_mono - self.last_change) < cooldown and not self._force_next_control:
                self.last_action = "cooldown"
                self._notify()
                return

        # Применение новой уставки
        await self._set_trv_temperature(climate_entity, t_trv)
        self.last_action = "set_temperature"

        LOGGER.debug(
            "set_temperature: entity=%s room=%.2f target=%.2f error=%.2f offset=%.2f correction=%.2f trv=%.2f rate=%.3f",
            climate_entity, t_room, t_target, e, offset, correction, t_trv, self._heating_rate
        )

        # Обновление heating rate (только если нагреваем)
        if e > deadband and not self.window_is_open and not self.boost_active:
            if self._prev_room_temp is not None and self._prev_time is not None:
                dt = (now_mono - self._prev_time) / 60.0  # в минутах
                if dt > 0:
                    dT = t_room - self._prev_room_temp
                    if dT > 0:  # только подъём температуры
                        current_rate = dT / dt
                        self._heating_rate = heating_alpha * current_rate + (1 - heating_alpha) * self._heating_rate

        # Автоматическое уменьшение offset со временем (decay)
        if enable_learning and not no_learn and self._last_offset_update > 0:
            days_since_update = (now_mono - self._last_offset_update) / (24 * 3600)
            if days_since_update > 1:  # Прошло более суток
                current_offset = self.storage.get_offset(self.entry.entry_id)
                if abs(current_offset) > OFFSET_DECAY_THRESHOLD:  # Если offset значительный
                    decay = OFFSET_DECAY_RATE * days_since_update
                    new_offset = current_offset * (1 - decay)
                    if abs(new_offset - current_offset) >= min_offset_change:
                        self.storage.set_offset(self.entry.entry_id, new_offset)
                        await self.storage.async_save()
                        self._last_offset_update = now_mono
                        LOGGER.info(
                            "Offset decay: days=%.1f decay=%.3f offset=%.2f -> %.2f",
                            days_since_update, decay, current_offset, new_offset
                        )

        # Сохраняем текущие значения для следующего тика
        self._prev_room_temp = t_room
        self._prev_time = now_mono

        self._notify()