from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, Tuple, List

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.components.climate.const import HVACMode

from .const import *

LOGGER = logging.getLogger(__name__)

CONF_HVAC_MODE = "hvac_mode"  # локально, чтобы не падать если в const.py ещё не добавили


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _round_step(v: float, step: float) -> float:
    if step <= 0:
        return v
    return round(v / step) * step


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_entity_list(value: Any) -> list[str]:
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


def _is_truthy_state(state: Any) -> bool:
    if state is None:
        return False
    return str(state).lower() in ("on", "open", "true", "1")


@dataclass
class Inputs:
    climate_entity: str
    climate_state: Any
    t_room: float
    t_target: float
    hvac_mode: str
    window_open: bool
    now_mono: float


class SmartOffsetController:
    def __init__(self, hass, entry, storage):
        self.hass = hass
        self.entry = entry
        self.storage = storage

        self.unsub = None

        # runtime state
        self.last_set: Optional[float] = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error: Optional[float] = None
        self.last_target_trv: Optional[float] = None
        self.change_count = 0

        # hvac mode anti-spam
        self.last_hvac_mode: Optional[str] = None

        # boost
        self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0

        # window
        self.window_is_open = False
        self._window_open_since: Optional[float] = None
        self._unsub_window = None
        self._window_entities: Tuple[str, ...] = tuple()

        # stability tracking
        self._last_room_target: Optional[float] = None
        self._stable_since: Optional[float] = None
        self._stable_target: Optional[float] = None
        self._stable_last_set: Optional[float] = None

        # history
        self._history_data: list[Dict[str, Any]] = []

        # ttt / dynamics
        self._heating_rate = 0.1
        self._prev_room_temp: Optional[float] = None
        self._prev_time: Optional[float] = None
        self._last_heating_rate_save: float = 0.0

        self._overshoot_count = 0
        self._learn_rate_slow = 0.1
        self._last_offset_update = 0.0

        # stuck logic (bias to force down)
        self._force_next_control = False
        self._stuck_active = False
        self._stuck_ref_temp: Optional[float] = None
        self._stuck_ref_time: Optional[float] = None
        self._stuck_bias = 0.0

        self._heat_episode: Optional[Dict[str, float]] = None
        self._minutes_per_degree = (
            self.storage.get_minutes_per_degree(self.entry.entry_id)
            if hasattr(self.storage, "get_minutes_per_degree")
            else 15.0
        )

        # options snapshot (read on init; still use opt() for runtime reads)
        self._ttt_alpha = float(self.opt(CONF_TTT_ALPHA))

        self.stable_learn_seconds = int(self.opt(CONF_STABLE_LEARN_SECONDS))
        self.stable_learn_alpha = float(self.opt(CONF_STABLE_LEARN_ALPHA))
        self.offset_decay_rate = float(self.opt(CONF_OFFSET_DECAY_RATE))
        self.offset_decay_threshold = float(self.opt(CONF_OFFSET_DECAY_THRESHOLD))
        self.offset_learn_threshold = float(self.opt(CONF_OFFSET_LEARN_THRESHOLD))
        self.max_stuck_bias = float(self.opt(CONF_MAX_STUCK_BIAS))
        self.ttt_soft_min = float(self.opt(CONF_TTT_SOFT_MIN))

    def opt(self, key: str) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return DEFAULTS.get(key)

    def _notify(self):
        now = time.time()
        offset = self.storage.get_offset(self.entry.entry_id)

        self._history_data.append(
            {
                "time": now,
                "error": self.last_error,
                "offset": offset,
                "trv_set": self.last_set,
                "action": self.last_action,
            }
        )

        if len(self._history_data) > 576:
            self._history_data = self._history_data[-576:]

        if len(self._history_data) % 10 == 0:
            self.hass.async_create_task(
                self.storage.set_history(self.entry.entry_id, self._history_data)
            )

        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # -------------------------
    # lifecycle
    # -------------------------
    async def async_start(self):
        self._history_data = self.storage.get_history(self.entry.entry_id) or []
        self._heating_rate = self.storage.get_heating_rate(self.entry.entry_id)
        self._overshoot_count = self.storage.get_overshoot_count(self.entry.entry_id)
        self._learn_rate_slow = float(
            self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW
        )

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

        await self.storage.set_heating_rate(
            self.entry.entry_id, self._heating_rate, reason="shutdown"
        )
        await self.storage.set_overshoot_count(self.entry.entry_id, self._overshoot_count)
        await self.storage.set_history(self.entry.entry_id, self._history_data)

        if self._unsub_window:
            try:
                self._unsub_window()
            except Exception:
                pass
            self._unsub_window = None

    async def trigger_once(self, force: bool = False):
        if force:
            self._force_next_control = True
        await self._tick(None)

    async def reset_offset(self):
        await self.storage.set_offset(self.entry.entry_id, 0.0, reason="manual_reset")
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

    # -------------------------
    # listeners / helpers
    # -------------------------
    def _cancel_boost(self):
        if self._boost_unsub:
            try:
                self._boost_unsub()
            except Exception:
                pass
            self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0

    def _reset_stability_tracking(self):
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None

    def _ensure_window_listener(self, window_entities: Optional[list[str]]):
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
                if _is_truthy_state(st.state):
                    return True
            return False

        async def _on_window_change(_event):
            is_open = _compute_open()
            now = self.hass.loop.time()

            if is_open != self.window_is_open:
                self.window_is_open = is_open
                self._window_open_since = now if is_open else None

            await self.trigger_once(force=True)
            self._notify()

        self._unsub_window = async_track_state_change_event(
            self.hass, list(entities), _on_window_change
        )

    async def _set_trv_temperature(self, entity_id: str, temp: float) -> bool:
        now = self.hass.loop.time()

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
            return True
        except Exception as e:
            LOGGER.error("Ошибка установки температуры на %s: %s", entity_id, e)
            self.last_action = "set_failed"
            return False

    async def _set_trv_hvac_mode(self, entity_id: str, mode: HVACMode | str) -> bool:
        mode_val = mode.value if isinstance(mode, HVACMode) else str(mode)

        if self.last_hvac_mode == mode_val:
            return False

        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": mode_val},
                blocking=True,
            )
            self.last_hvac_mode = mode_val
            return True
        except Exception as e:
            LOGGER.error("Ошибка установки hvac_mode=%s на %s: %s", mode_val, entity_id, e)
            self.last_action = "set_hvac_mode_failed"
            return False

    # -------------------------
    # inputs / mode selection
    # -------------------------
    async def _read_inputs(self, now_mono: float) -> Optional[Inputs]:
        climate_entity = self.entry.data[CONF_CLIMATE]

        room_entities = _normalize_entity_list(self.entry.data.get(CONF_ROOM_SENSORS, []))
        if not room_entities:
            self.last_action = "skipped_no_room_sensors"
            return None

        temps: list[float] = []
        for entity in room_entities:
            st = self.hass.states.get(entity)
            if st is None:
                continue
            t = _to_float(st.state)
            if t is not None:
                temps.append(t)

        if not temps:
            self.last_action = "skipped_no_valid_room_temp"
            return None

        t_room = sum(temps) / len(temps)

        climate_state = self.hass.states.get(climate_entity)
        if climate_state is None:
            self.last_action = "skipped_unavailable_climate"
            return None

        t_target = float(self.opt(CONF_ROOM_TARGET))

        # hvac_mode from options (virtual)
        mode_raw = self.entry.options.get(CONF_HVAC_MODE, HVACMode.HEAT.value)
        hvac_mode = mode_raw.value if isinstance(mode_raw, HVACMode) else str(mode_raw).lower()

        # window state
        window_entities = _normalize_entity_list(self.opt(CONF_WINDOW_SENSORS))
        self._ensure_window_listener(window_entities)

        window_open = False
        for ent in window_entities:
            st = self.hass.states.get(ent)
            if st is None:
                continue
            if _is_truthy_state(st.state):
                window_open = True
                break

        if window_open != self.window_is_open:
            self.window_is_open = window_open
            self._window_open_since = now_mono if window_open else None

        return Inputs(
            climate_entity=climate_entity,
            climate_state=climate_state,
            t_room=t_room,
            t_target=t_target,
            hvac_mode=hvac_mode,
            window_open=window_open,
            now_mono=now_mono,
        )

    # -------------------------
    # ttt learning (heat episodes)
    # -------------------------
    def _maybe_start_heat_episode(self, now_mono: float, t_room: float, t_target: float, deadband: float):
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

    async def _maybe_finish_heat_episode(self, now_mono: float, t_room: float, t_target: float, deadband: float):
        if self._heat_episode is None:
            return
        if t_room + deadband < t_target:
            return

        t0 = self._heat_episode["t0"]
        e0 = max(0.1, self._heat_episode["e0"])
        minutes = (now_mono - t0) / 60.0
        mpd = _clamp(minutes / e0, 2.0, 120.0)

        self._minutes_per_degree = (
            self._ttt_alpha * mpd + (1.0 - self._ttt_alpha) * self._minutes_per_degree
        )

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

    # -------------------------
    # learning helpers
    # -------------------------
    def _window_no_learn_seconds(self) -> int:
        """
        Backward compatible:
        - if user config looks like "minutes" (small number), treat as minutes
        - if looks like "seconds" (large number), treat as seconds
        """
        v = int(self.opt(CONF_WINDOW_OPEN_NO_LEARN_MIN) or DEFAULT_WINDOW_OPEN_NO_LEARN_SEC)
        if v <= 180:  # <= 3 hours => assume minutes (intended)
            return v * 60
        return v  # assume seconds (legacy configs like 600)

    async def _handle_stable_learning(self, inp: Inputs, deadband: float):
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))
        no_learn_summer = bool(self.opt(CONF_NO_LEARN_SUMMER) or DEFAULT_NO_LEARN_SUMMER)

        now_dt = datetime.now()
        is_summer = no_learn_summer and 6 <= now_dt.month <= 8

        long_window_open = (
            self.window_is_open
            and self._window_open_since is not None
            and (inp.now_mono - self._window_open_since >= self._window_no_learn_seconds())
        )

        if not enable_learning or is_summer or long_window_open or self.last_set is None:
            return

        if self._stable_since is None or self._stable_target != inp.t_target:
            self._stable_since = inp.now_mono
            self._stable_target = inp.t_target
            self._stable_last_set = self.last_set
            return

        if inp.now_mono - self._stable_since < self.stable_learn_seconds:
            return

        implied_offset = _clamp(self.last_set - inp.t_room, MIN_OFFSET, MAX_OFFSET)
        current_offset = self.storage.get_offset(self.entry.entry_id)
        min_offset_change = float(self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE)

        if abs(implied_offset - current_offset) <= self.offset_learn_threshold:
            self._stuck_bias = 0.0
            self._reset_stability_tracking()
            return

        new_offset = current_offset + self.stable_learn_alpha * (implied_offset - current_offset)
        if abs(new_offset - current_offset) >= min_offset_change:
            await self.storage.set_offset(self.entry.entry_id, new_offset, reason="stable_learn")
            self.last_action = "stable_learn"
            self._last_offset_update = inp.now_mono

        self._stuck_bias = 0.0
        self._reset_stability_tracking()

    async def _handle_offset_decay(self, now_mono: float, enable_learning: bool):
        if not enable_learning or self._last_offset_update <= 0:
            return

        days_since_update = (now_mono - self._last_offset_update) / (24 * 3600)
        if days_since_update <= 1:
            return

        current_offset = self.storage.get_offset(self.entry.entry_id)
        min_offset_change = float(self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE)

        if abs(current_offset) <= self.offset_decay_threshold:
            return

        decay = self.offset_decay_rate * days_since_update
        mult = max(0.0, 1.0 - decay)
        new_offset = current_offset * mult

        if abs(new_offset - current_offset) >= min_offset_change:
            await self.storage.set_offset(self.entry.entry_id, new_offset, reason="offset_decay")
            self._last_offset_update = now_mono
            LOGGER.info(
                "Offset decay: days=%.1f decay=%.3f offset=%.2f -> %.2f",
                days_since_update,
                decay,
                current_offset,
                new_offset,
            )

    async def _update_heating_rate(self, t_room: float, now_mono: float, heating_alpha: float):
        if self._prev_room_temp is None or self._prev_time is None:
            return

        dt_min = (now_mono - self._prev_time) / 60.0
        if dt_min <= 0 or dt_min < 0.25 or dt_min > 30.0:
            return

        dT = t_room - self._prev_room_temp
        if dT <= 0:
            return

        current_rate = dT / dt_min
        self._heating_rate = heating_alpha * current_rate + (1.0 - heating_alpha) * self._heating_rate

        if (now_mono - self._last_heating_rate_save) >= 300:
            self._last_heating_rate_save = now_mono
            await self.storage.set_heating_rate(
                self.entry.entry_id, self._heating_rate, reason="auto_update"
            )

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
    ) -> float:
        # only when overheated (need to go down), but temperature doesn't drop
        if e < -deadband:
            if not self._stuck_active:
                self._stuck_active = True
                self._stuck_ref_temp = t_room
                self._stuck_ref_time = now_mono
                return t_trv

            if self._stuck_ref_time and (now_mono - self._stuck_ref_time >= stuck_seconds):
                ref_temp = self._stuck_ref_temp if self._stuck_ref_temp is not None else t_room
                if t_room >= (ref_temp - stuck_min_drop):
                    self._stuck_bias = min(self._stuck_bias + stuck_step, self.max_stuck_bias)
                    t_trv = _round_step(_clamp(t_trv - stuck_step, trv_min, trv_max), step_min)
                    self.last_action = "stuck_overtemp_down"
                self._stuck_ref_temp = t_room
                self._stuck_ref_time = now_mono
            return t_trv

        # reset when not overheated
        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0
        return t_trv

    # -------------------------
    # mode handlers
    # -------------------------
    async def _handle_hvac_off(self, inp: Inputs):
        self._cancel_boost()
        await self._set_trv_hvac_mode(inp.climate_entity, HVACMode.OFF)
        self.last_action = "hvac_off"
        self._stuck_bias = 0.0
        self._reset_stability_tracking()

    async def _handle_window_open(self, inp: Inputs) -> bool:
        if not inp.window_open:
            return False

        self._cancel_boost()

        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        t_trv = _round_step(trv_min, step_min)
        self.last_target_trv = t_trv

        if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
            await self._set_trv_temperature(inp.climate_entity, t_trv)

        self.last_action = "window_open"
        self._stuck_bias = 0.0
        self._reset_stability_tracking()
        return True

    async def _handle_boost(self, inp: Inputs) -> bool:
        if not self.boost_active or inp.now_mono >= self.boost_until:
            return False

        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        t_trv = _round_step(_clamp(trv_max, trv_min, trv_max), step_min)
        self.last_target_trv = t_trv

        self._reset_stability_tracking()
        self._stuck_bias = 0.0

        if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
            await self._set_trv_temperature(inp.climate_entity, t_trv)

        self.last_action = "boost"
        return True

    async def _handle_deadband_hold(self, inp: Inputs, deadband: float) -> bool:
        e = inp.t_target - inp.t_room
        if abs(e) > deadband:
            return False

        offset = self.storage.get_offset(self.entry.entry_id)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        baseline = _round_step(_clamp(inp.t_target + offset, trv_min, trv_max), step_min)

        target_changed = (
            self._last_room_target is not None and abs(inp.t_target - self._last_room_target) > 1e-9
        )
        self._last_room_target = inp.t_target

        if target_changed or self.last_set is None:
            self.last_target_trv = baseline
            if self.last_set is None or abs(baseline - self.last_set) >= (step_min - 1e-9):
                await self._set_trv_temperature(inp.climate_entity, baseline)
                self.last_action = "deadband_rebase" if target_changed else "deadband_init"
            self._reset_stability_tracking()
            return True

        self.last_target_trv = self.last_set
        self.last_action = "hold"

        await self._handle_stable_learning(inp, deadband)
        return True

    async def _handle_active_control(self, inp: Inputs):
        t_room = inp.t_room
        t_target = inp.t_target
        e = t_target - t_room

        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        step_max = float(self.opt(CONF_STEP_MAX) or DEFAULT_STEP_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        learn_rate_fast = float(self.opt(CONF_LEARN_RATE_FAST) or DEFAULT_LEARN_RATE_FAST)
        min_offset_change = float(self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        cooldown = float(self.opt(CONF_COOLDOWN_SEC) or DEFAULT_COOLDOWN_SEC)
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))

        heating_alpha = float(self.opt(CONF_HEATING_ALPHA) or DEFAULT_HEATING_ALPHA)
        overshoot_threshold = float(self.opt(CONF_OVERSHOOT_THRESHOLD) or DEFAULT_OVERSHOOT_THRESHOLD)
        predict_minutes = int(self.opt(CONF_PREDICT_MINUTES) or DEFAULT_PREDICT_MINUTES)

        stuck_enable = bool(self.opt(CONF_STUCK_ENABLE))
        stuck_seconds = int(self.opt(CONF_STUCK_SECONDS) or DEFAULT_STUCK_SECONDS)
        stuck_min_drop = float(self.opt(CONF_STUCK_MIN_DROP) or DEFAULT_STUCK_MIN_DROP)
        stuck_step = float(self.opt(CONF_STUCK_STEP) or DEFAULT_STUCK_STEP)

        # TTT learning episode
        self._maybe_start_heat_episode(inp.now_mono, t_room, t_target, deadband)
        self._update_heat_episode(t_room)
        await self._maybe_finish_heat_episode(inp.now_mono, t_room, t_target, deadband)

        offset = self.storage.get_offset(self.entry.entry_id)

        # overshoot auto-tune (reduce slow learn rate if overheating often)
        if t_room > t_target + overshoot_threshold:
            new_count = await self.storage.increment_overshoot_count(self.entry.entry_id)
            self._overshoot_count = new_count
            if self._overshoot_count > 3:
                self._learn_rate_slow = max(0.01, self._learn_rate_slow * 0.9)
                LOGGER.info("Auto-tune: снижен learn_rate_slow до %.3f из-за перегрева", self._learn_rate_slow)
                self._overshoot_count = 0

        learn_rate = learn_rate_fast if abs(e) > deadband * 2 else self._learn_rate_slow

        # active learning: adjust offset towards reducing error
        if enable_learning and abs(e) > deadband:
            learn_direction = 1 if e > 0 else -1
            new_offset = _clamp(
                offset + learn_direction * learn_rate * abs(e), MIN_OFFSET, MAX_OFFSET
            )
            if abs(new_offset - offset) >= min_offset_change:
                offset = new_offset
                await self.storage.set_offset(self.entry.entry_id, offset, reason="active_learning")
                self._last_offset_update = inp.now_mono

        # correction (P-like)
        correction = _clamp(0.5 * e, -step_max, step_max)

        # soft landing for small TTT
        if e > 0:
            predicted_minutes_ttt = e * self._minutes_per_degree
            if predicted_minutes_ttt < self.ttt_soft_min:
                factor = _clamp(predicted_minutes_ttt / self.ttt_soft_min, 0.3, 1.0)
                correction *= factor

        # overshoot prevention from heating_rate
        if e > 0 and self._heating_rate > 0.001:
            predicted_time = e / self._heating_rate  # minutes
            if predicted_time < predict_minutes:
                factor = max(0.5, 1.0 - (predict_minutes - predicted_time) / predict_minutes)
                correction *= factor

        t_trv = _round_step(t_target + offset + correction, step_min)

        # stuck logic: when overheated but room temp doesn't drop, force more aggressive down
        if stuck_enable and (not self.window_is_open) and (not self.boost_active):
            t_trv = await self._handle_stuck_detection(
                t_room,
                e,
                deadband,
                stuck_seconds,
                stuck_min_drop,
                stuck_step,
                inp.now_mono,
                t_trv,
                step_min,
                trv_min,
                trv_max,
            )

        # apply accumulated stuck_bias in overheat zone
        if e < -deadband and self._stuck_bias > 0:
            t_trv = _round_step(_clamp(t_trv - self._stuck_bias, trv_min, trv_max), step_min)

        t_trv = _clamp(t_trv, trv_min, trv_max)
        self.last_target_trv = t_trv

        # anti spam (step threshold + cooldown)
        if self.last_set is not None:
            if abs(t_trv - self.last_set) < (step_min - 1e-9):
                self.last_action = "skipped_no_change"
                return
            if (inp.now_mono - self.last_change) < cooldown and not self._force_next_control:
                self.last_action = "cooldown"
                return

        success = await self._set_trv_temperature(inp.climate_entity, t_trv)
        if success:
            self.last_action = "set_temperature"

        # update dynamics only while heating is actually needed
        if e > deadband and not self.window_is_open and not self.boost_active:
            await self._update_heating_rate(t_room, inp.now_mono, heating_alpha)

        await self._handle_offset_decay(inp.now_mono, enable_learning)

    # -------------------------
    # main tick
    # -------------------------
    async def _tick(self, _):
        now_mono = self.hass.loop.time()

        inp = await self._read_inputs(now_mono)
        if not inp:
            self._notify()
            return

        # compute error for sensors
        e = inp.t_target - inp.t_room
        self.last_error = round(e, 3)

        # virtual hvac_mode -> enforce TRV mode
        if inp.hvac_mode == HVACMode.OFF.value:
            await self._handle_hvac_off(inp)
            self._prev_room_temp = inp.t_room
            self._prev_time = now_mono
            self._notify()
            return  # IMPORTANT: hard-stop; don't continue control

        # ensure heat (no spam inside _set_trv_hvac_mode)
        await self._set_trv_hvac_mode(inp.climate_entity, HVACMode.HEAT)

        # window / boost / hold / control
        if await self._handle_window_open(inp):
            self._prev_room_temp = inp.t_room
            self._prev_time = now_mono
            self._notify()
            return

        if await self._handle_boost(inp):
            self._prev_room_temp = inp.t_room
            self._prev_time = now_mono
            self._notify()
            return

        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        if await self._handle_deadband_hold(inp, deadband):
            self._prev_room_temp = inp.t_room
            self._prev_time = now_mono
            self._notify()
            return

        await self._handle_active_control(inp)

        self._prev_room_temp = inp.t_room
        self._prev_time = now_mono
        self._notify()