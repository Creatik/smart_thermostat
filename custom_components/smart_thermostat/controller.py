from __future__ import annotations

import asyncio
import logging
import time

from datetime import datetime, timedelta
from typing import Any, Optional, Tuple, Dict

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.event import (
    async_track_time_interval,
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.components.climate.const import HVACMode

from .const import *
from .helpers import (
    clamp as _clamp,
    round_step as _round_step,
    to_float as _to_float,
    normalize_entity_list as _normalize_entity_list,
    is_truthy_state as _is_truthy_state,
    saturated_offset_step as _saturated_offset_step,
    commit_debounced_bool as _commit_debounced_bool,
    apply_soft_landing as _apply_soft_landing,
    valve_heat_demand as _valve_heat_demand,
    underheat_trv_floor as _underheat_trv_floor,
    overshoot_trv_ceiling as _overshoot_trv_ceiling,
    approach_trv_ceiling as _approach_trv_ceiling,
    approach_offset_toward as _approach_offset_toward,
    room_is_rising as _room_is_rising_helper,
    local_is_rising as _local_is_rising_helper,
    offset_write_within_budget as _offset_write_within_budget,
    offset_deadband_trim_adjustment as _offset_deadband_trim_adjustment,
    trv_heat_flowing as _trv_heat_flowing,
    usable_trv_local as _usable_trv_local,
    local_is_stuck as _local_is_stuck,
    weather_suppressed as _weather_suppressed,
    ttt_sample_mpd as _ttt_sample_mpd,
    blend_minutes_per_degree as _blend_minutes_per_degree,
    should_cold_start_jerk as _should_cold_start_jerk,
    in_night_no_learn_window as _in_night_no_learn_window,
    arrival_slot_kind as _arrival_slot_kind,
    heating_rate_sample as _heating_rate_sample,
    ema_heating_rate as _ema_heating_rate,
    schedule_target_step as _schedule_target_step,
    should_arrival_warmup as _should_arrival_warmup,
    window_regime_offset as _window_regime_offset,
    window_control_target as _window_control_target,
    valve_learning_blocked as _valve_learning_blocked,
    valve_ref_setpoint as _valve_ref_setpoint,
    heat_delivery_state as _heat_delivery_state,
)
from .inputs import Inputs
from .pid import PIDController
from .feedforward import Feedforward

LOGGER = logging.getLogger(__name__)

CONF_HVAC_MODE = "hvac_mode"


class SmartOffsetController:
    def __init__(self, hass, entry, storage):
        self.hass = hass
        self.entry = entry
        self.storage = storage

        self.unsub = None
        self._startup_attempts = 0
        self._sensor_retry_unsub = None
        self._sensor_retry_count = 0
        self._sensor_entities_cache: list[str] = []

        # runtime state
        self.last_set: Optional[float] = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error: Optional[float] = None
        self.last_target_trv: Optional[float] = None
        self.change_count = 0
        # верификация уставки TRV и управление клапаном через переключатель
        self.trv_reported_setpoint: Optional[float] = None
        self.trv_setpoint_sync = "unknown"
        self.last_baseline: Optional[float] = None
        self._last_valve_switch_time = 0.0
        # анти-дребезг: направление последнего изменения уставки
        self._last_set_direction = 0
        self._last_set_direction_time = 0.0

        # hvac mode anti-spam
        self.last_hvac_mode: Optional[str] = None
        self._prev_hvac_mode_config: Optional[str] = None

        # boost
        self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0

        # valve exercise (автопрокрутка клапана)
        self._valve_exercise_active = False
        self._valve_exercise_until = 0.0
        self._valve_exercise_unsub = None

        # window
        self.window_is_open = False
        self._window_open_since: Optional[float] = None
        self._window_pending_since: Optional[float] = None
        self._window_primed = False
        self._window_debounce_unsub = None
        self._unsub_window = None
        self._window_entities: Tuple[str, ...] = tuple()
        # local TRV: полка и защёлка «датчик врёт»
        self._local_track_value: Optional[float] = None
        self._local_track_since: Optional[float] = None
        self._local_track_set_lo: Optional[float] = None
        self._local_track_set_hi: Optional[float] = None
        self._local_stuck = False
        self._local_invalid_logged = False
        # погода снята, пока клапан упёрт в максимум
        self._weather_suppressed = False

        # stability tracking
        self._last_room_target: Optional[float] = None
        self._stable_since: Optional[float] = None
        self._stable_target: Optional[float] = None
        self._stable_last_set: Optional[float] = None

        # ttt / dynamics
        self._heating_rate = 0.1
        self._prev_room_temp: Optional[float] = None
        self._prev_local_temp: Optional[float] = None
        self._prev_time: Optional[float] = None
        # offset на начало тика: бюджет обучения «≤ max_offset_step ЗА ТИК»
        # (инвариант 3), когда в одном тике пишут active_learning и approach_trim
        self._tick_offset_snapshot: Optional[float] = None
        self._last_heating_rate_save: float = 0.0

        self._overshoot_count = 0
        self._learn_rate_slow = 0.1
        # До первого тика — None: раньше здесь был 0.0, из-за чего
        # days_since_update в _handle_offset_decay равнялся аптайму HA в днях
        # и сразу после рестарта срабатывал ложный распад offset по времени
        self._last_offset_update: Optional[float] = None
        # Аккумулятор дробных поправок обучения: поправка меньше
        # min_offset_change раньше молча отбрасывалась каждый тик,
        # из-за чего медленное обучение фактически не работало
        self._pending_offset_delta = 0.0
        # auto-tune: монотонное время последнего перегрева
        # (нужно для восстановления learn_rate_slow)
        self._last_overshoot_mono: Optional[float] = None
        # Диагностика «источник не даёт тепло» (карта улучшений P0):
        # flowing / absent / unknown — виден в сенсоре heat_delivery
        self.heat_delivery = "unknown"
        self._valve_open_since: Optional[float] = None
        self._heat_local_prev: Optional[float] = None
        self._heat_local_prev_mono: Optional[float] = None
        self._step_up_mono: Optional[float] = None
        self._heat_absent_warn_mono: Optional[float] = None
        # Скачки сырой цели расписания (t_target), не t_effective —
        # иначе эко/погода дают ложный step и сбрасывают freeze
        self._prev_schedule_target: Optional[float] = None
        self._learn_freeze_until: Optional[float] = None
        # True, пока активен boost после скачка цели вверх (для last_action)
        self._schedule_boost = False
        # Occupancy: предыдущий is_present (None = ещё не знаем после старта)
        self._prev_present: Optional[bool] = None
        self._arrival_boost = False
        self._last_arrival_boost_mono: Optional[float] = None
        # Холодный старт: рывок по большому недогреву + контроль local TRV
        self._cold_start_boost = False
        self._last_cold_start_mono: Optional[float] = None

        # PID + feedforward
        self.pid = PIDController(
            float(self.opt(CONF_PID_KP) or DEFAULT_PID_KP),
            float(self.opt(CONF_PID_KI) or DEFAULT_PID_KI),
            float(self.opt(CONF_PID_KD) or DEFAULT_PID_KD),
        )
        self.ff = Feedforward(
            self.hass, self.opt, storage=self.storage, entry_id=self.entry.entry_id
        )

        # stuck logic
        self._force_next_control = False
        self._stuck_active = False
        self._stuck_ref_temp: Optional[float] = None
        self._stuck_ref_time: Optional[float] = None
        self._stuck_bias = 0.0
        # stuck-underheat: комната должна греться (e > deadband), но не греется
        self._stuck_cold_active = False
        self._stuck_cold_ref_temp: Optional[float] = None
        self._stuck_cold_ref_time: Optional[float] = None

        self._heat_episode: Optional[Dict[str, float]] = None
        self._minutes_per_degree = (
            self.storage.get_minutes_per_degree(self.entry.entry_id)
            if hasattr(self.storage, "get_minutes_per_degree")
            else 15.0
        )

        self._unsub_sensor_appear = None
        self._sensor_listener_entities: Tuple[str, ...] = tuple()
        # options snapshot
        self._ttt_alpha = float(self.opt(CONF_TTT_ALPHA))

        self.stable_learn_seconds = int(self.opt(CONF_STABLE_LEARN_SECONDS))
        self.stable_learn_alpha = float(self.opt(CONF_STABLE_LEARN_ALPHA))
        self.offset_decay_rate = float(self.opt(CONF_OFFSET_DECAY_RATE))
        self.offset_decay_threshold = float(self.opt(CONF_OFFSET_DECAY_THRESHOLD))
        self.offset_learn_threshold = float(self.opt(CONF_OFFSET_LEARN_THRESHOLD))
        self.ttt_soft_min = float(self.opt(CONF_TTT_SOFT_MIN) or 5.0)
        self.predict_minutes = int(self.opt(CONF_PREDICT_MINUTES) or 15)

    def opt(self, key: str) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return DEFAULTS.get(key)

    def _notify(self):
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    async def _end_tick(self, inp: Inputs, now_mono: float) -> None:
        """Закрытие тика: prev-state, запись history_*, notify сущностей."""
        self._prev_room_temp = inp.t_room
        self._prev_time = now_mono
        self._prev_local_temp = self._read_trv_local_temp(inp.climate_entity)
        try:
            offset = float(self.storage.get_offset(self.entry.entry_id))
            trv = (
                self.last_set
                if self.last_set is not None
                else self.last_target_trv
            )
            await self.storage.append_tick(
                self.entry.entry_id,
                error=self.last_error,
                offset=offset,
                trv_set=trv,
                action=str(self.last_action or ""),
            )
        except Exception:
            LOGGER.debug(
                "append_tick failed for %s", self.entry.entry_id, exc_info=True
            )
        self._notify()

    # -------------------------
    # Переключатель клапана (явная настройка)
    # -------------------------
    def _get_valve_switch(self) -> Optional[str]:
        """Entity_id переключателя клапана (например, switch.*_state у Tuya-TRV через Z2M).

        Настраивается явно опцией valve_switch_entity. Прежняя авто-детекция
        «Яндекс-питания» ошибочно захватывала switch.*_state Zigbee2MQTT-устройств
        и сама открывала клапан, из-за чего он не закрывался.
        """
        val = self.opt(CONF_VALVE_SWITCH_ENTITY)
        if isinstance(val, str) and val.strip():
            return val.strip()
        return None

    async def _set_valve_switch(self, on: bool, force: bool = False) -> None:
        """Открыть/закрыть клапан через настроенный переключатель."""
        entity = self._get_valve_switch()
        if not entity:
            return

        state = self.hass.states.get(entity)
        if state is None or state.state not in ("on", "off"):
            return

        if state.state == ("on" if on else "off"):
            return

        # защита от дребезга: не чаще одного переключения в 30 секунд
        now = self.hass.loop.time()
        if not force and (now - self._last_valve_switch_time) < 30:
            return
        self._last_valve_switch_time = now

        try:
            await self.hass.services.async_call(
                "switch",
                "turn_on" if on else "turn_off",
                {"entity_id": entity},
                blocking=True,
            )
            LOGGER.info("Клапан %s → %s", entity, "открыт" if on else "закрыт")
        except Exception as e:
            LOGGER.warning("Не удалось переключить клапан %s: %s", entity, e)

    # -------------------------
    # lifecycle
    # -------------------------
    async def async_start(self):
        self._heating_rate = self.storage.get_heating_rate(self.entry.entry_id)
        self._overshoot_count = self.storage.get_overshoot_count(self.entry.entry_id)
        if hasattr(self.storage, "get_change_count"):
            self.change_count = self.storage.get_change_count(self.entry.entry_id)
        self._learn_rate_slow = float(
            self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW
        )
        # восстанавливаем auto-tune learn_rate_slow, если настроенная база
        # (CONF_LEARN_RATE_SLOW) не менялась пользователем — иначе начинаем заново
        tuned = (
            self.storage.get_learn_rate_slow(self.entry.entry_id)
            if hasattr(self.storage, "get_learn_rate_slow")
            else None
        )
        if tuned and abs(float(tuned.get("base", 0.0)) - self._learn_rate_slow) < 1e-9:
            self._learn_rate_slow = max(
                LEARN_RATE_FLOOR, float(tuned.get("tuned", self._learn_rate_slow))
            )

        interval = int(self.opt(CONF_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC)
        
        # СНАЧАЛА запускаем интервал (гарантирует продолжение работы даже при ошибке в первом тике)
        self.unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=interval)
        )
        
        # ЗАТЕМ делаем один немедленный тик для быстрой инициализации
        await self._tick(None)
        
        LOGGER.info(
            "Controller %s started with %d sec interval (initial state: %s)",
            self.entry.entry_id,
            interval,
            self.last_action,
        )

    async def async_stop(self):
        self._cancel_boost()
        self._cancel_valve_exercise()
        if self.unsub:
            self.unsub()
            self.unsub = None

        await self.storage.set_heating_rate(
            self.entry.entry_id, self._heating_rate, reason="shutdown"
        )
        await self.storage.set_overshoot_count(
            self.entry.entry_id, self._overshoot_count
        )
        if hasattr(self.storage, "set_change_count"):
            await self.storage.set_change_count(
                self.entry.entry_id, self.change_count
            )

        if self._unsub_sensor_appear:
            try:
                self._unsub_sensor_appear()
            except Exception:
                pass
            self._unsub_sensor_appear = None
        self._sensor_listener_entities = tuple()

        if self._unsub_window:
            try:
                self._unsub_window()
            except Exception:
                pass
            self._unsub_window = None
        self._cancel_window_debounce()

        self._stop_sensor_retry()

    async def trigger_once(self, force: bool = False):
        if force:
            self._force_next_control = True
        await self._tick(None)

    async def reset_offset(self):
        await self.storage.set_offset(self.entry.entry_id, 0.0, reason="manual_reset")
        self._pending_offset_delta = 0.0
        self._last_offset_update = None
        self.last_action = "reset_offset"
        await self.trigger_once(force=True)
        self._notify()

    async def start_boost(
        self, duration: Optional[int] = None, *, trigger: bool = True
    ):
        if duration is None:
            duration = int(self.opt(CONF_BOOST_DURATION_SEC) or DEFAULT_BOOST_DURATION_SEC)
        # Авто-boost на скачке расписания дольше обычного ручного (до 1 ч)
        duration = max(30, min(int(duration), 3600))

        self._cancel_boost()
        self.boost_active = True
        self.boost_until = self.hass.loop.time() + float(duration)

        async def _end(_):
            self._cancel_boost()
            await self.trigger_once(force=True)
            self._notify()

        self._boost_unsub = async_call_later(self.hass, float(duration), _end)
        # Изнутри _tick trigger=False — иначе реentrancy; boost подхватит
        # тот же тик в _handle_boost
        if trigger:
            await self.trigger_once(force=True)
            self._notify()

    def _update_heat_delivery(self, inp: Inputs, deadband: float) -> None:
        """Диагностика «источник не даёт тепло» (карта улучшений P0).

        Отвечает на вопрос пользователя «почему не греется»: контур
        командует клапан полностью открытым при недогреве, а батарея
        остаётся холодной (local < room+margin) — значит тепло не
        приходит от котла/циркуляции, это не баг offset.
        Гварды анти-ложных: boost, разгон local, grace после step-up.
        """
        t_local = self._read_trv_local_temp(inp.climate_entity)
        if t_local is None or inp.t_room is None:
            self._valve_open_since = None
            self.heat_delivery = "unknown"
            return
        try:
            e = float(inp.t_effective) - float(inp.t_room)
            local = float(t_local)
        except (TypeError, ValueError):
            self.heat_delivery = "unknown"
            return

        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        desired = float(inp.t_effective) + offset
        ref = (
            max(self.last_set, desired)
            if self.last_set is not None
            else desired
        )
        # «Командуем греть на полном ходу»: недогрев + уставка ≥ local+margin
        valve_full_open = (e > deadband) and (
            ref >= local + float(VALVE_TRAVEL_MARGIN)
        )
        if valve_full_open:
            if self._valve_open_since is None:
                self._valve_open_since = inp.now_mono
        else:
            self._valve_open_since = None

        # Рост local между наблюдениями → батарея разгоняется, не absent
        local_rising = False
        if (
            self._heat_local_prev is not None
            and self._heat_local_prev_mono is not None
        ):
            dt = inp.now_mono - self._heat_local_prev_mono
            if 0 < dt <= 1800 and (local - self._heat_local_prev) >= float(
                HEAT_SOURCE_LOCAL_RISE_MIN
            ):
                local_rising = True
        self._heat_local_prev = local
        self._heat_local_prev_mono = inp.now_mono

        since_step = (
            inp.now_mono - self._step_up_mono
            if self._step_up_mono is not None
            else None
        )
        state = _heat_delivery_state(
            valve_open_sec=(
                inp.now_mono - self._valve_open_since
                if self._valve_open_since is not None
                else None
            ),
            heat_flowing=_trv_heat_flowing(
                inp.t_room, local, margin=HEAT_FLOW_LOCAL_MARGIN
            ),
            boosting=self.boost_active,
            local_rising=local_rising,
            since_step_up_sec=since_step,
            absent_after_sec=float(HEAT_SOURCE_ABSENT_AFTER_SEC),
            step_up_grace_sec=float(HEAT_SOURCE_GRACE_AFTER_STEP_SEC),
        )
        if state != self.heat_delivery:
            LOGGER.info(
                "Heat delivery: %s → %s (e=%.2f, ref=%.1f, local=%.1f)",
                self.heat_delivery,
                state,
                e,
                ref,
                local,
            )
        self.heat_delivery = state
        if state == "absent":
            if (
                self._heat_absent_warn_mono is None
                or inp.now_mono - self._heat_absent_warn_mono
                >= float(HEAT_SOURCE_WARN_INTERVAL_SEC)
            ):
                self._heat_absent_warn_mono = inp.now_mono
                self.last_action = "heat_source_absent"
                LOGGER.warning(
                    "Heat source ABSENT: клапан полностью открыт %d мин, "
                    "local %.1f ≈ room %.1f — котёл/циркуляция не дают тепло "
                    "(offset не виноват)",
                    int(float(HEAT_SOURCE_ABSENT_AFTER_SEC) / 60),
                    local,
                    float(inp.t_room),
                )

    def _is_learn_frozen(self, now_mono: float) -> bool:
        """Обучение заморожено: скачок цели вниз и/или ночь с открытыми окнами.

        Ночью окна открыты 24/7 без датчиков — уличный холод не должен
        разгонять offset (иначе к утру уставка «сломана»).
        """
        if (
            self._learn_freeze_until is not None
            and now_mono < self._learn_freeze_until
        ):
            return True
        if bool(self.opt(CONF_NIGHT_OPEN_WINDOWS)):
            try:
                from homeassistant.util import dt as dt_util

                now_local = dt_util.now()
            except Exception:
                from datetime import datetime as _dt

                now_local = _dt.now().astimezone()
            if _in_night_no_learn_window(
                now_local,
                self.opt(CONF_NIGHT_NO_LEARN_START) or DEFAULT_NIGHT_NO_LEARN_START,
                self.opt(CONF_NIGHT_NO_LEARN_END) or DEFAULT_NIGHT_NO_LEARN_END,
            ):
                return True
        return False

    async def _maybe_handle_target_step(self, inp: Inputs) -> None:
        """Реакция на скачок сырой цели расписания (эко ↔ комфорт).

        Сравниваем ``t_target`` (room_target/пресет), не ``t_effective``:
        эко occupancy и погода иначе дают ложные ±3°C → спам boost и
        сброс learn_freeze.

        Вверх (≥ +2°C) при недогреве: авто-boost (TRV=max) + подъём offset
        так, чтобы после boost клапан не закрылся снова из‑за offset≈−6.

        Вниз (≤ −2°C): заморозка обучения + снять boost — иначе эко-«перегрев»
        и залипший TRV=max при цели 18.
        """
        cur = float(inp.t_target)
        prev = self._prev_schedule_target
        self._prev_schedule_target = cur
        direction = _schedule_target_step(
            prev, cur, threshold=float(TARGET_STEP_THRESHOLD)
        )
        if direction is None:
            return

        if direction == "down":
            self._learn_freeze_until = (
                inp.now_mono + float(LEARN_FREEZE_AFTER_TARGET_DROP_SEC)
            )
            self._pending_offset_delta = 0.0
            if self.boost_active:
                self._cancel_boost()
            self.last_action = "learn_freeze"
            LOGGER.info(
                "Schedule step down %.1f→%.1f: freeze learning for %ds",
                prev,
                cur,
                int(LEARN_FREEZE_AFTER_TARGET_DROP_SEC),
            )
            return

        # Реальный скачок расписания вверх: снимаем заморозку
        self._learn_freeze_until = None
        # Для диагностики heat_delivery: grace-окно после step-up
        # (батарея ещё разгоняется, «нет тепла» — ложная тревога)
        self._step_up_mono = inp.now_mono
        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        # Недогрев относительно контура (effective), пол offset — тоже
        e = float(inp.t_effective) - float(inp.t_room)
        if e <= deadband:
            LOGGER.info(
                "Schedule step up %.1f→%.1f: no warmup (error=%.2f, window=%s)",
                prev,
                cur,
                e,
                inp.window_open,
            )
            return

        # 1) Offset-пол: TRV = t_effective+offset(+PID) ≥ room+margin
        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        floor_offset = _clamp(
            (inp.t_room + TARGET_STEP_VALVE_MARGIN) - float(inp.t_effective),
            MIN_OFFSET,
            MAX_OFFSET,
        )
        if offset < floor_offset - 1e-9:
            await self.storage.set_offset(
                self.entry.entry_id, floor_offset, reason="target_step_warmup"
            )
            self._pending_offset_delta = 0.0
            self._last_offset_update = inp.now_mono
            LOGGER.warning(
                "Schedule step up %.1f→%.1f: offset %.2f→%.2f (TRV≥room+%.1f)",
                prev,
                cur,
                offset,
                floor_offset,
                TARGET_STEP_VALVE_MARGIN,
            )

        # 2) Авто-boost: сразу TRV=max и открыть клапан на TARGET_STEP_BOOST_SEC
        if not self.boost_active:
            self._schedule_boost = True
            self.last_action = "target_step_warmup"
            await self.start_boost(int(TARGET_STEP_BOOST_SEC), trigger=False)
            LOGGER.warning(
                "Schedule step up %.1f→%.1f: auto-boost %ds (room=%.1f, need +%.1f)",
                prev,
                cur,
                int(TARGET_STEP_BOOST_SEC),
                inp.t_room,
                e,
            )

    # =========================
    # ПРЕСЕТЫ (Comfort/Eco/Away/Sleep)
    # =========================
    def active_preset(self) -> Optional[str]:
        """Активный пресет (None, если ручной режим 'none')."""
        preset = self.storage.get_preset(self.entry.entry_id)
        if preset and preset in PRESET_MODES and preset != PRESET_NONE:
            return preset
        return None

    def active_target(self) -> float:
        """Базовая цель: температура активного пресета или ручная уставка."""
        preset = self.active_preset()
        if preset:
            option_key = PRESET_TEMP_OPTION.get(preset)
            if option_key:
                try:
                    return float(self.opt(option_key))
                except (ValueError, TypeError):
                    pass
        return float(self.opt(CONF_ROOM_TARGET))

    def preset_target(self, preset: str) -> Optional[float]:
        """Температура указанного пресета (или None)."""
        option_key = PRESET_TEMP_OPTION.get(preset)
        if not option_key:
            return None
        try:
            return float(self.opt(option_key))
        except (ValueError, TypeError):
            return None

    async def set_preset(self, preset: str) -> None:
        """Переключить активный пресет (persisted в storage)."""
        if preset not in PRESET_MODES:
            LOGGER.warning("Некорректный пресет %r для %s", preset, self.entry.entry_id)
            return
        await self.storage.set_preset(self.entry.entry_id, preset)
        self._reset_stability_tracking()
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
        self._schedule_boost = False
        self._arrival_boost = False
        self._cold_start_boost = False

    def _read_trv_local_temp(self, climate_entity: str) -> Optional[float]:
        """Локальная температура клапана, либо None если датчик врёт.

        −0.01 и застывшая полка при гуляющей уставке не температура радиатора:
        посадка и холодный старт иначе принимают обрыв за «лёд» или «уже горячо».
        """
        state = self.hass.states.get(climate_entity)
        if state is None or state.state in ("unavailable", "unknown"):
            return None
        raw: Optional[float] = None
        for attr in ("current_temperature", "local_temperature"):
            raw = _to_float((state.attributes or {}).get(attr))
            if raw is not None:
                break
        usable = _usable_trv_local(raw, lo=LOCAL_TEMP_MIN, hi=LOCAL_TEMP_MAX)
        if usable is None:
            if raw is not None and not self._local_invalid_logged:
                self._local_invalid_logged = True
                LOGGER.warning(
                    "TRV %s: local %s вне %.0f..%.0f — датчик игнорируется",
                    climate_entity,
                    raw,
                    LOCAL_TEMP_MIN,
                    LOCAL_TEMP_MAX,
                )
            return None
        self._local_invalid_logged = False

        now = self.hass.loop.time()
        eps = float(LOCAL_STUCK_EPSILON)
        if (
            self._local_track_value is None
            or self._local_track_since is None
            or abs(usable - self._local_track_value) > eps
        ):
            self._local_track_value = usable
            self._local_track_since = now
            self._local_track_set_lo = self.last_set
            self._local_track_set_hi = self.last_set
            if self._local_stuck:
                self._local_stuck = False
                LOGGER.info(
                    "TRV %s: local снова живой (%.1f)", climate_entity, usable
                )
            return usable

        if self.last_set is not None:
            if self._local_track_set_lo is None or self.last_set < self._local_track_set_lo:
                self._local_track_set_lo = self.last_set
            if self._local_track_set_hi is None or self.last_set > self._local_track_set_hi:
                self._local_track_set_hi = self.last_set
        span = 0.0
        if (
            self._local_track_set_lo is not None
            and self._local_track_set_hi is not None
        ):
            span = self._local_track_set_hi - self._local_track_set_lo
        commanded_above = (
            self._local_track_set_lo is not None
            and self._local_track_set_lo >= usable + LOCAL_STUCK_COMMAND_GAP
        )
        flat = now - self._local_track_since
        stuck = _local_is_stuck(
            flat,
            span,
            stuck_after_sec=LOCAL_STUCK_SEC,
            min_set_span=LOCAL_STUCK_SET_SPAN,
            commanded_above=commanded_above,
            command_stuck_sec=LOCAL_STUCK_COMMAND_SEC,
        )
        if stuck and not self._local_stuck:
            self._local_stuck = True
            LOGGER.warning(
                "TRV %s: local %.1f не меняется %.0f мин при размахе уставки "
                "%.1f — датчик игнорируется",
                climate_entity,
                usable,
                flat / 60.0,
                span,
            )
        if stuck:
            return None
        return usable

    def _command_at_max(self, climate_entity: Optional[str] = None) -> bool:
        """Клапан уже открыт до упора: по своей уставке или по тому, что на TRV.

        После рестарта last_set пустой, а голова всё ещё на 30°. Без этой
        проверки первый тик снова включает погоду и холодный старт.
        """
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        limit = trv_max - TRV_SATURATED_MARGIN - 1e-9
        if self.last_set is not None and self.last_set >= limit:
            return True
        if not climate_entity:
            return False
        state = self.hass.states.get(climate_entity)
        if state is None:
            return False
        reported = _to_float((state.attributes or {}).get("temperature"))
        return reported is not None and reported >= limit

    def _cancel_valve_exercise(self):
        if self._valve_exercise_unsub:
            try:
                self._valve_exercise_unsub()
            except Exception:
                pass
            self._valve_exercise_unsub = None
        self._valve_exercise_active = False
        self._valve_exercise_until = 0.0

    async def _start_valve_exercise(self, inp: Inputs):
        """Открыть клапан на максимум на короткое время, чтобы он не залипал."""
        exercise_sec = int(
            self.opt(CONF_VALVE_EXERCISE_SEC) or DEFAULT_VALVE_EXERCISE_SEC
        )
        exercise_sec = max(10, min(exercise_sec, 600))
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        t_trv = _round_step(_clamp(trv_max, trv_min, trv_max), step_min)

        self._valve_exercise_active = True
        self._valve_exercise_until = self.hass.loop.time() + float(exercise_sec)
        self.last_action = "valve_exercise"
        self.last_target_trv = t_trv
        await self._set_trv_temperature(inp.climate_entity, t_trv)
        # прокрутка клапана требует открытого клапана
        await self._set_valve_switch(True, force=True)

        async def _end(_):
            self._cancel_valve_exercise()
            await self.storage.set_valve_exercise(
                self.entry.entry_id, time.time()
            )
            await self.trigger_once(force=True)
            self._notify()

        self._valve_exercise_unsub = async_call_later(
            self.hass, float(exercise_sec), _end
        )

    def _reset_stability_tracking(self):
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None
        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0
        self._stuck_cold_active = False
        self._stuck_cold_ref_temp = None
        self._stuck_cold_ref_time = None
        self._reset_pid()

    def _reset_pid(self):
        """Сброс состояния PID (интеграл, производная, эталон)."""
        self.pid.reset()

    def _ensure_window_listener(self, window_entities: Optional[list[str]]):
        entities = tuple([e for e in _normalize_entity_list(window_entities) if e])
        if entities == self._window_entities:
            return

        if self._unsub_window:
            try:
                self._unsub_window()
            except Exception:
                pass
            finally:
                self._unsub_window = None

        self._window_entities = entities
        if not entities:
            return

        async def _on_window_change(_event):
            # Не коммитим сырой contact: дребезг не должен закрывать клапан.
            changed = self._apply_window_commit(
                self.hass.loop.time(), self._peek_room_temp()
            )
            self._arm_window_debounce()
            if changed:
                await self.trigger_once(force=True)
                self._notify()

        self._unsub_window = async_track_state_change_event(
            self.hass, list(entities), _on_window_change
        )

    def _peek_room_temp(self) -> Optional[float]:
        ents = getattr(self, "_sensor_entities_cache", None) or _normalize_entity_list(
            self.entry.data.get(CONF_ROOM_SENSORS, [])
        )
        temps: list[float] = []
        bad = ("unavailable", "unknown", "none", "", "uninitialized", "NaN")
        for entity in ents:
            st = self.hass.states.get(entity)
            if st is None or st.state in bad:
                continue
            val = _to_float(st.state)
            if val is not None:
                temps.append(val)
        if not temps:
            return None
        return sum(temps) / len(temps)

    def _window_raw_open(self) -> bool:
        for ent in self._window_entities:
            st = self.hass.states.get(ent)
            if st is None:
                continue
            if _is_truthy_state(st.state):
                return True
        return False

    def _cancel_window_debounce(self) -> None:
        unsub = self._window_debounce_unsub
        self._window_debounce_unsub = None
        if unsub is None:
            return
        try:
            unsub()
        except Exception:
            pass

    def _arm_window_debounce(self) -> None:
        if self._window_pending_since is None:
            self._cancel_window_debounce()
            return
        if self._window_debounce_unsub is not None:
            return

        async def _fire(_now):
            self._window_debounce_unsub = None
            changed = self._apply_window_commit(
                self.hass.loop.time(), self._peek_room_temp()
            )
            if self._window_pending_since is not None:
                self._arm_window_debounce()
            if changed:
                await self.trigger_once(force=True)
                self._notify()

        wait = (
            WINDOW_OPEN_DEBOUNCE_SEC
            if self._window_raw_open()
            else WINDOW_CLOSE_DEBOUNCE_SEC
        )
        self._window_debounce_unsub = async_call_later(self.hass, float(wait), _fire)

    def _apply_window_commit(
        self, now: float, room: Optional[float] = None, *, allow_prime: bool = False
    ) -> bool:
        """Сырой contact → устойчивое window_is_open. True, если коммит сменился."""
        raw = self._window_raw_open()
        if not self._window_primed:
            if not allow_prime:
                return False
            # Уже открытое окно после рестарта не ждёт debounce.
            self._window_primed = True
            self._window_pending_since = None
            changed = raw != self.window_is_open
            self.window_is_open = raw
            self._window_open_since = now if raw else None
            return changed

        wait = WINDOW_OPEN_DEBOUNCE_SEC if raw else WINDOW_CLOSE_DEBOUNCE_SEC
        committed, pending = _commit_debounced_bool(
            raw,
            self.window_is_open,
            self._window_pending_since,
            now,
            wait,
        )
        self._window_pending_since = pending
        if committed == self.window_is_open:
            return False

        if committed:
            self.window_is_open = True
            self._window_open_since = now
            LOGGER.info("Window open (после debounce)")
            return True

        self.window_is_open = False
        self._window_open_since = None
        LOGGER.info("Window closed (после debounce)")
        return True

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
            old_set = self.last_set
            self.last_set = temp
            self.last_change = now
            if old_set is not None:
                self._last_set_direction = (
                    1 if temp > old_set else (-1 if temp < old_set else 0)
                )
                self._last_set_direction_time = now
            self.change_count += 1
            self._force_next_control = False
            # персистим счётчик порциями по 10 (и при остановке): иначе после
            # reload критерий здоровья «total_changes растёт медленно» не наблюдаем
            if self.change_count % 10 == 0 and hasattr(
                self.storage, "set_change_count"
            ):
                await self.storage.set_change_count(
                    self.entry.entry_id, self.change_count
                )
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
                blocking=False,
            )
            self.last_hvac_mode = mode_val
            return True
        except Exception as e:
            LOGGER.error(
                "Ошибка установки hvac_mode=%s на %s: %s", mode_val, entity_id, e
            )
            self.last_action = "set_hvac_mode_failed"
            return False

    # -------------------------
    # Активный опрос датчиков при старте
    # -------------------------
    def _start_sensor_retry(self):
        """Запускает активный опрос датчиков с коротким интервалом до их появления"""
        if self._sensor_retry_unsub is not None:
            return  # Уже запущен
        
        async def _retry_tick(_):
            self._sensor_retry_count += 1
            LOGGER.debug(
                "Sensor retry #%d for %s (total attempts: %d)",
                self._sensor_retry_count,
                self.entry.entry_id,
                self._startup_attempts + self._sensor_retry_count,
            )
            await self._tick(None)
            
            # Останавливаем опрос если датчики появились или прошло 10 попыток (~50 сек)
            if self.last_action not in ("waiting_sensors", "init") or self._sensor_retry_count >= 10:
                self._stop_sensor_retry()

        # Короткий интервал 5 сек для быстрого обнаружения датчиков
        self._sensor_retry_unsub = async_track_time_interval(
            self.hass, _retry_tick, timedelta(seconds=5)
        )
        LOGGER.info(
            "Started active sensor polling for %s (5 sec interval)",
            self.entry.entry_id,
        )

    def _stop_sensor_retry(self):
        """Останавливает активный опрос датчиков"""
        if self._sensor_retry_unsub is not None:
            self._sensor_retry_unsub()
            self._sensor_retry_unsub = None
            self._sensor_retry_count = 0
            LOGGER.debug("Stopped active sensor polling for %s", self.entry.entry_id)

    def _ensure_sensor_listener(self, sensor_entities: list[str]):
        entities = tuple([e for e in _normalize_entity_list(sensor_entities) if e])

        # если список не изменился — ничего не делаем
        if entities == self._sensor_listener_entities and self._unsub_sensor_appear is not None:
            return

        # если изменился — снимаем старую подписку
        if self._unsub_sensor_appear:
            try:
                self._unsub_sensor_appear()
            except Exception:
                pass
            self._unsub_sensor_appear = None

        self._sensor_listener_entities = entities
        if not entities:
            return

        async def _on_sensor_change(event):
            entity_id = event.data.get("entity_id")
            new_state = event.data.get("new_state")
            if not new_state:
                return

            # отбрасываем недоступные
            if new_state.state in ("unavailable", "unknown", "none", "", "uninitialized", "NaN"):
                return

            t = _to_float(new_state.state)
            if t is None or not (-40.0 <= t <= 80.0):
                return

            LOGGER.info(
                "Sensor %s became available for %s (value: %.1f°C) → trigger tick",
                entity_id, self.entry.entry_id, t
            )
            await self.trigger_once(force=True)

        self._unsub_sensor_appear = async_track_state_change_event(
            self.hass, list(entities), _on_sensor_change
        )

    # -------------------------
    # inputs / mode selection
    # -------------------------
    async def _read_inputs(self, now_mono: float) -> Optional[Inputs]:
        climate_entity = self.entry.data[CONF_CLIMATE]

        room_entities = _normalize_entity_list(
            self.entry.data.get(CONF_ROOM_SENSORS, [])
        )
        self._ensure_sensor_listener(room_entities)
        if not room_entities:
            self.last_action = "no_room_sensors"
            LOGGER.warning("No room sensors configured for %s", self.entry.entry_id)
            return None

        # Кэшируем сенсоры для слушателя появления
        self._sensor_entities_cache = room_entities

        temps: list[float] = []
        unavailable = []
        invalid = []
        
        for entity in room_entities:
            st = self.hass.states.get(entity)
            if st is None:
                unavailable.append(f"{entity}=None")
                continue
                
            if st.state in ("unavailable", "unknown", "none", "", "uninitialized", "NaN"):
                unavailable.append(f"{entity}={st.state}")
                continue
                
            t = _to_float(st.state)
            if t is None:
                invalid.append(f"{entity}='{st.state}'")
                continue
                
            if not (-40.0 <= t <= 80.0):
                invalid.append(f"{entity}={t}°C (out of range)")
                continue
                
            temps.append(t)

        if not temps:
            self._startup_attempts += 1
            
            if self._startup_attempts % 3 == 1:
                LOGGER.debug(
                    "No valid temperatures for %s (attempt #%d). Unavailable: %s | Invalid: %s",
                    self.entry.entry_id,
                    self._startup_attempts,
                    unavailable[:3],
                    invalid[:3],
                )
            
            return None

        # Сенсоры доступны — останавливаем активный опрос
        self._stop_sensor_retry()
        
        if self._startup_attempts > 0:
            LOGGER.info(
                "Sensors became available for %s after %d attempts: %.1f°C",
                self.entry.entry_id,
                self._startup_attempts,
                sum(temps) / len(temps),
            )
            self._startup_attempts = 0

        t_room = sum(temps) / len(temps)

        climate_state = self.hass.states.get(climate_entity)
        if climate_state is None or climate_state.state in ("unavailable", "unknown"):
            self.last_action = "climate_unavailable"
            LOGGER.debug(
                "Climate entity %s unavailable for %s (state: %s)",
                climate_entity,
                self.entry.entry_id,
                climate_state.state if climate_state else "None",
            )
            return None

        t_target = self.active_target()

        mode_raw = self.entry.options.get(CONF_HVAC_MODE, HVACMode.HEAT.value)
        hvac_mode = (
            mode_raw.value if isinstance(mode_raw, HVACMode) else str(mode_raw).lower()
        )

        window_entities = _normalize_entity_list(self.opt(CONF_WINDOW_SENSORS))
        self._ensure_window_listener(window_entities)
        self._apply_window_commit(now_mono, t_room, allow_prime=True)
        self._arm_window_debounce()
        window_open = self.window_is_open

        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        at_max = self._command_at_max(climate_entity)
        below_release = (
            self.last_set is not None
            and self.last_set <= trv_max - WEATHER_SUPPRESS_RELEASE + 1e-9
        )
        deadband_card = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        room_short = float(t_room) + deadband_card < float(t_target)
        suppressed = _weather_suppressed(
            self._weather_suppressed, at_max, below_release, room_short
        )
        if suppressed != self._weather_suppressed:
            LOGGER.info(
                "Weather comp %s (set=%s, max=%.1f, short=%s)",
                "off" if suppressed else "on",
                self.last_set,
                trv_max,
                room_short,
            )
        self._weather_suppressed = suppressed

        t_effective = self.ff.effective_target(
            t_target, hvac_mode, skip_weather=suppressed
        )
        eco = self.preset_target(PRESET_ECO)
        if eco is None:
            eco = float(self.opt(CONF_PRESET_ECO_TEMP) or DEFAULT_PRESET_ECO_TEMP)
        # Окно открыто большую часть времени: комфорт 23 в улицу не гоним.
        # Карточка остаётся на цели расписания, контур держит не выше эко.
        t_effective = _window_control_target(t_effective, eco, window_open)
        self.control_target = t_effective

        return Inputs(
            climate_entity=climate_entity,
            climate_state=climate_state,
            t_room=t_room,
            t_target=t_target,
            t_effective=t_effective,
            hvac_mode=hvac_mode,
            window_open=window_open,
            now_mono=now_mono,
            trv_reported_setpoint=_to_float(
                climate_state.attributes.get("temperature")
            ),
        )

    # -------------------------
    # ttt learning (heat episodes)
    # -------------------------
    def _approach_mpd(self) -> float | None:
        """Память мин/°C для посадки. Выброс ниже пола не участвует в ETA."""
        try:
            mpd = float(self._minutes_per_degree)
        except (TypeError, ValueError):
            return None
        if mpd < TTT_MPD_MIN:
            return None
        return mpd

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
        if t_room + deadband < t_target:
            return

        t0 = self._heat_episode["t0"]
        e0 = max(0.1, self._heat_episode["e0"])
        rise = float(self._heat_episode.get("max_room", t_room)) - float(
            self._heat_episode.get("room0", t_room)
        )
        minutes = (now_mono - t0) / 60.0
        # Короткий эпизод у мёртвой зоны не учим: пол 0.1° и clamp в 2 мин/°
        # вытеснили живой темп детской (08.11, mpd 40 → 2).
        mpd = _ttt_sample_mpd(
            minutes,
            rise,
            min_minutes=self.ttt_soft_min,
            min_rise=TTT_MIN_RISE,
            mpd_lo=TTT_MPD_MIN,
            mpd_hi=120.0,
        )
        if mpd is None:
            LOGGER.info(
                "TTT skip: minutes=%.1f rise=%.2f e0=%.2f — эпизод короче физики радиатора",
                minutes,
                rise,
                e0,
            )
            self._heat_episode = None
            return

        if self._minutes_per_degree < TTT_MPD_MIN:
            self._minutes_per_degree = mpd
        else:
            self._minutes_per_degree = (
                self._ttt_alpha * mpd
                + (1.0 - self._ttt_alpha) * self._minutes_per_degree
            )
        # Согласовать heating_rate (°C/мин) с эпизодом
        if minutes >= 1.0:
            sample = _heating_rate_sample(
                rise,
                minutes,
                rate_lo=HEATING_RATE_MIN,
                rate_hi=HEATING_RATE_MAX,
            )
            if sample is not None:
                self._heating_rate = _ema_heating_rate(
                    self._heating_rate, sample, float(self._ttt_alpha)
                )

        if hasattr(self.storage, "set_minutes_per_degree"):
            await self.storage.set_minutes_per_degree(
                self.entry.entry_id, self._minutes_per_degree
            )

        LOGGER.info(
            "TTT learn: minutes=%.1f rise=%.2f e0=%.2f => mpd=%.1f, ema_mpd=%.1f, hr=%.4f",
            minutes,
            rise,
            e0,
            mpd,
            self._minutes_per_degree,
            self._heating_rate,
        )

        self._heat_episode = None

    # -------------------------
    # learning helpers (УЛУЧШЕННЫЕ)
    # -------------------------
    async def _handle_stable_learning(self, inp: Inputs, deadband: float):
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))
        # ИСПРАВЛЕНО: заменено DEFAULT_NO_LEARN_SUMMER на безопасное значение
        no_learn_summer = bool(
            self.opt(CONF_NO_LEARN_SUMMER) or False
        )

        now_dt = datetime.now()
        is_summer = no_learn_summer and 6 <= now_dt.month <= 8

        # Открытое окно — отдельный offset (commit_window_regime), не пауза.
        # Иначе при окне «большую часть жизни» hold-обучение никогда не идёт.
        if (
            not enable_learning
            or is_summer
            or self.last_set is None
        ):
            return

        # ГВАРДЫ против самоусиления (раньше offset улетал в предел из-за их отсутствия):
        # 1) комната реально у цели, а не перегрета
        e_now = inp.t_effective - inp.t_room
        if abs(e_now) > max(0.1, deadband * 0.5):
            return
        # 2) текущая уставка не прижата к пределам TRV (нерепрезентативна)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        if abs(self.last_set - trv_min) < 0.01 or abs(self.last_set - trv_max) < 0.01:
            return
        # 3) уставка равна baseline (не завышена PID-коррекцией активной фазы)
        offset_now = self.storage.get_offset(self.entry.entry_id)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        if abs(self.last_set - (inp.t_effective + offset_now)) > step_min + 1e-9:
            return

        if self._stable_since is None or self._stable_target != inp.t_effective:
            self._stable_since = inp.now_mono
            self._stable_target = inp.t_effective
            self._stable_last_set = self.last_set
            return

        if inp.now_mono - self._stable_since < self.stable_learn_seconds:
            return

        implied_offset = _clamp(self.last_set - inp.t_room, MIN_OFFSET, MAX_OFFSET)
        current_offset = self.storage.get_offset(self.entry.entry_id)
        min_offset_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )

        if abs(implied_offset - current_offset) <= self.offset_learn_threshold:
            self._stuck_bias = 0.0
            self._reset_stability_tracking()
            return

        new_offset = current_offset + self.stable_learn_alpha * (
            implied_offset - current_offset
        )
        if abs(new_offset - current_offset) >= min_offset_change:
            await self.storage.set_offset(
                self.entry.entry_id, new_offset, reason="stable_learn"
            )
            self.last_action = "stable_learn"
            self._last_offset_update = inp.now_mono
            # offset изменён другим механизмом — накопленная дробная
            # поправка активного обучения больше не актуальна
            self._pending_offset_delta = 0.0

        self._stuck_bias = 0.0
        self._reset_stability_tracking()

    async def _handle_offset_decay(self, now_mono: float, enable_learning: bool, inp: Optional[Inputs] = None):
        """Распад смещения по времени И при избыточном смещении в мёртвой зоне"""
        if not enable_learning:
            return

        # Первый вызов после старта — только задаём точку отсчёта. Раньше
        # _last_offset_update инициализировался 0.0, days_since_update
        # получался равен аптайму HA в днях, и сразу после рестарта
        # срабатывал распад по времени при любом |offset| > threshold —
        # пинг-понг с active_learning у предела (видно в истории гостиной:
        # offset_decay_time → active_learning каждые сутки).
        if self._last_offset_update is None:
            self._last_offset_update = now_mono
            return

        current_offset = self.storage.get_offset(self.entry.entry_id)

        # Сценарий 1: распад по времени (как было)
        days_since_update = (now_mono - self._last_offset_update) / (24 * 3600)
        if days_since_update > 1 and abs(current_offset) > self.offset_decay_threshold:
            decay = self.offset_decay_rate * days_since_update
            mult = max(0.0, 1.0 - decay)
            proposed = current_offset * mult
            new_offset = self._budgeted_offset(current_offset, proposed)
            if new_offset is not None:
                await self.storage.set_offset(
                    self.entry.entry_id, new_offset, reason="offset_decay_time"
                )
                self._last_offset_update = now_mono
                LOGGER.info(
                    "Offset decay (time): days=%.1f offset=%.2f → %.2f",
                    days_since_update,
                    current_offset,
                    new_offset,
                )
                return

        # Сценарий 2: АГРЕССИВНЫЙ распад при избыточном смещении в мёртвой зоне
        if inp is not None and abs(current_offset) > OFFSET_SATURATED_TRIGGER:
            # t_effective — та же ошибка, что у active/hold (не сырой t_target)
            e = inp.t_effective - inp.t_room
            deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)

            # Шаг к полу недогрева, не слепое ×0.92 в обе стороны:
            # плюс не режем ниже room+margin−target, минус не поднимаем при жаре.
            stepped = _saturated_offset_step(
                current_offset,
                e,
                deadband,
                saturated_trigger=OFFSET_SATURATED_TRIGGER,
                underheat_margin=UNDERHEAT_TRV_MARGIN,
                max_step=float(
                    self.opt(CONF_MAX_OFFSET_STEP) or DEFAULT_MAX_OFFSET_STEP
                ),
            )
            if stepped is not None:
                new_offset = self._budgeted_offset(current_offset, stepped)
                if new_offset is not None:
                    await self.storage.set_offset(
                        self.entry.entry_id, new_offset, reason="offset_decay_aggressive"
                    )
                    self._last_offset_update = now_mono
                    # offset изменён другим механизмом — сбрасываем накопитель
                    self._pending_offset_delta = 0.0
                    LOGGER.warning(
                        "AGGRESSIVE offset decay: error=%.2f°C, offset=%.2f → %.2f (deadband=%.2f)",
                        e,
                        current_offset,
                        new_offset,
                        deadband,
                    )

    async def _handle_offset_trim_deadband(self, inp: Inputs, deadband: float) -> None:
        """Мягкая подрезка 2 < |offset| ≤ 3 в hold (раньше мёртвый код в active)."""
        if not bool(self.opt(CONF_ENABLE_LEARNING)):
            return
        if self._is_learn_frozen(inp.now_mono):
            return
        e = inp.t_effective - inp.t_room
        if abs(e) > deadband + 1e-9:
            return

        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        adjustment = _offset_deadband_trim_adjustment(
            offset,
            e,
            float(self._learn_rate_slow),
            soft_trigger=OFFSET_TRIM_SOFT_TRIGGER,
            saturated_trigger=OFFSET_SATURATED_TRIGGER,
            trim_max=OFFSET_TRIM_MAX,
        )
        if adjustment == 0.0:
            return

        min_offset_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )
        max_offset_step = float(
            self.opt(CONF_MAX_OFFSET_STEP) or DEFAULT_MAX_OFFSET_STEP
        )
        adjustment = _clamp(adjustment, -max_offset_step, max_offset_step)
        self._pending_offset_delta = _clamp(
            self._pending_offset_delta + adjustment,
            -max_offset_step,
            max_offset_step,
        )
        if abs(self._pending_offset_delta) < min_offset_change:
            return

        # Бюджет тика (инвариант 3): суммарный шаг offset за тик ≤ max_offset_step,
        # даже когда писателей несколько (active_learning + approach_trim + этот
        # trim). Излишек сверх бюджета отбрасываем: pending и так ограничен
        # max_offset_step, а держать «хвост» на следующий тик значит копить шаг.
        if self._tick_offset_snapshot is not None:
            spent = abs(offset - float(self._tick_offset_snapshot))
            budget = max(0.0, max_offset_step - spent)
            if budget < min_offset_change - 1e-9:
                return
            self._pending_offset_delta = _clamp(
                self._pending_offset_delta, -budget, budget
            )
            if abs(self._pending_offset_delta) < min_offset_change:
                return

        new_offset = _clamp(
            offset + self._pending_offset_delta, MIN_OFFSET, MAX_OFFSET
        )
        applied = new_offset - offset
        if abs(applied) < min_offset_change:
            self._pending_offset_delta = 0.0
            return

        await self.storage.set_offset(
            self.entry.entry_id, new_offset, reason="offset_trim"
        )
        self._last_offset_update = inp.now_mono
        self._pending_offset_delta -= applied
        self.last_action = "offset_trim"
        LOGGER.info(
            "Offset trim (deadband): error=%.2f offset=%.2f → %.2f",
            e,
            offset,
            new_offset,
        )

    async def _apply_approach_offset(
        self, inp: Inputs, room_rising: bool = False
    ) -> None:
        """При ранней посадке подтянуть offset к room+margin−target.

        Уставка уже срезана потолком; без этого offset остаётся +2…+6
        и следующий тик снова хочет TRV=26 (спальня 04.11).

        Два гварда — не ослаблять:

        1. **Evidence**: учим вниз только когда комната РЕАЛЬНО растёт при
           срезанной уставке — значит добивает накопленное тепло и offset
           честно велик. На падающей комнате (окно приоткрыто, мороз) trim
           утопил бы offset и дал недогрев, а недогрев хуже перелёта:
           там посадка режет только уставку, не обучение.
        2. **Бюджет тика**: суммарно ≤ max_offset_step за тик вместе с
           active_learning / deadband trim (инвариант 3), а не «каждый
           писатель по max_offset_step».
        """
        if not bool(self.opt(CONF_ENABLE_LEARNING)):
            return
        if not room_rising:
            return
        if self._is_learn_frozen(inp.now_mono):
            return
        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        max_step = float(self.opt(CONF_MAX_OFFSET_STEP) or DEFAULT_MAX_OFFSET_STEP)
        min_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )
        if self._tick_offset_snapshot is not None:
            spent = abs(offset - float(self._tick_offset_snapshot))
            max_step = max(0.0, max_step - spent)
        if max_step < min_change - 1e-9:
            return
        new_offset = _clamp(
            _approach_offset_toward(
                offset,
                inp.t_room,
                inp.t_effective,
                trv_margin=UNDERHEAT_TRV_MARGIN,
                max_step=max_step,
                min_change=min_change,
            ),
            MIN_OFFSET,
            MAX_OFFSET,
        )
        if abs(new_offset - offset) < min_change - 1e-9:
            return
        await self.storage.set_offset(
            self.entry.entry_id, new_offset, reason="approach_trim"
        )
        self._last_offset_update = inp.now_mono
        self._pending_offset_delta = 0.0
        LOGGER.info(
            "Approach trim: offset %.2f → %.2f (room=%.1f target=%.1f, комната растёт)",
            offset,
            new_offset,
            inp.t_room,
            inp.t_effective,
        )

    def _room_is_rising(self, inp: Inputs) -> bool:
        """Комната реально растёт между тиками — evidence для ранней посадки.

        Порог в °C/мин (``APPROACH_RISE_RATE_MIN``), а не в °C за тик: спальня
        на подходе растёт ~0.04 °C за 4-минутный тик, а квант датчика 0.01 °C
        на коротком интервале выглядел бы как «рост». ``heating_rate`` — EMA и
        переживает часы покоя, поэтому предиктивной отсечке и approach_trim
        нужен независимый факт роста именно сейчас.
        """
        return _room_is_rising_helper(
            self._prev_room_temp,
            self._prev_time,
            inp.now_mono,
            inp.t_room,
            rate_min=APPROACH_RISE_RATE_MIN,
            dt_min_lo=APPROACH_RISE_DT_MIN,
        )

    def _local_is_rising(self, inp: Inputs, t_local: Optional[float]) -> bool:
        """Клапан сам теплеет. Рост комнаты при холодном local — не чугун."""
        return _local_is_rising_helper(
            self._prev_local_temp,
            self._prev_time,
            inp.now_mono,
            t_local,
            rate_min=APPROACH_RISE_RATE_MIN,
            dt_min_lo=APPROACH_RISE_DT_MIN,
        )

    def _budgeted_offset(self, current: float, proposed: float) -> Optional[float]:
        """Сжать запись offset до остатка max_offset_step в этом тике."""
        max_step = float(self.opt(CONF_MAX_OFFSET_STEP) or DEFAULT_MAX_OFFSET_STEP)
        min_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )
        spent = 0.0
        if self._tick_offset_snapshot is not None:
            spent = abs(float(current) - float(self._tick_offset_snapshot))
        return _offset_write_within_budget(
            current,
            proposed,
            spent=spent,
            max_step=max_step,
            min_change=min_change,
        )

    def _is_likely_heating(self, t_room: float) -> bool:
        """TRV реально выше комнаты — иначе «нагрев» в логах при закрытом клапане."""
        for sp in (self.last_set, self.last_target_trv):
            if sp is not None and float(sp) > float(t_room) + 0.2:
                return True
        return False

    async def _update_heating_rate(
        self, t_room: float, now_mono: float, heating_alpha: float
    ):
        """Оценка °C/мин по ΔT между тиками (только пока реально греем).

        Важно вызывать ДО anti-spam return: при skipped_no_change уставка
        стабильна, комната растёт — как раз лучшие выборки; раньше rate
        почти не обновлялся и залипал / разъезжался с minutes_per_degree.
        """
        if self._prev_room_temp is None or self._prev_time is None:
            return

        dt_min = (now_mono - self._prev_time) / 60.0
        dT = t_room - self._prev_room_temp
        sample = _heating_rate_sample(
            dT,
            dt_min,
            dt_min_lo=HEATING_RATE_DT_MIN,
            dt_min_hi=HEATING_RATE_DT_MAX,
            dtemp_min=HEATING_RATE_DTEMP_MIN,
            rate_lo=HEATING_RATE_MIN,
            rate_hi=HEATING_RATE_MAX,
        )
        if sample is None:
            return

        self._heating_rate = _ema_heating_rate(
            self._heating_rate, sample, heating_alpha
        )
        # Держим TTT-метрику согласованной: mpd ≈ 1/rate.
        # Выброс ниже пола не усредняем — иначе 2 мин/° ещё долго отравляет посадку.
        if self._heating_rate > HEATING_RATE_MIN:
            blended = _blend_minutes_per_degree(
                self._minutes_per_degree,
                self._heating_rate,
                mpd_min=TTT_MPD_MIN,
            )
            if blended is not None:
                self._minutes_per_degree = blended

        if (now_mono - self._last_heating_rate_save) >= 300:
            self._last_heating_rate_save = now_mono
            await self.storage.set_heating_rate(
                self.entry.entry_id, self._heating_rate, reason="auto_update"
            )
            if hasattr(self.storage, "set_minutes_per_degree"):
                await self.storage.set_minutes_per_degree(
                    self.entry.entry_id, self._minutes_per_degree
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
        e_demand: Optional[float] = None,
    ) -> Tuple[float, bool]:
        if e < -deadband:
            if not self._stuck_active:
                self._stuck_active = True
                self._stuck_ref_temp = t_room
                self._stuck_ref_time = now_mono
                return t_trv, False

            if self._stuck_ref_time and (
                now_mono - self._stuck_ref_time >= stuck_seconds
            ):
                ref_temp = (
                    self._stuck_ref_temp if self._stuck_ref_temp is not None else t_room
                )
                if t_room >= (ref_temp - stuck_min_drop):
                    t_trv = _round_step(
                        _clamp(t_trv - stuck_step, trv_min, trv_max), step_min
                    )
                    self.last_action = "stuck_overtemp_down"
                    self._stuck_ref_temp = t_room
                    self._stuck_ref_time = now_mono
                    return t_trv, True

            return t_trv, False

        # Stuck-underheat: ошибка от цели карточки, не от погодной надбавки.
        e_heat = e if e_demand is None else e_demand
        # (e > deadband), но за stuck_seconds не поднялась даже на stuck_min_drop
        # — вероятно, команда уставки потеряна (Zigbee) или клапан закрыт.
        # Переотправляем уставку на следующем тике и открываем клапан, если
        # он настроен. Уставку не трогаем — PID уже вычислил правильную.
        if e_heat > deadband:
            # Уже на максимуме — переотправка тепло не создаёт. Потерянную
            # Zigbee-команду ловит сверка reported vs last_set.
            if t_trv >= trv_max - TRV_SATURATED_MARGIN - 1e-9:
                self._stuck_cold_active = False
                self._stuck_cold_ref_temp = None
                self._stuck_cold_ref_time = None
                return t_trv, False
            if not self._stuck_cold_active:
                self._stuck_cold_active = True
                self._stuck_cold_ref_temp = t_room
                self._stuck_cold_ref_time = now_mono
            elif (
                self._stuck_cold_ref_time is not None
                and (now_mono - self._stuck_cold_ref_time) >= stuck_seconds
            ):
                ref_temp = (
                    self._stuck_cold_ref_temp
                    if self._stuck_cold_ref_temp is not None
                    else t_room
                )
                if t_room <= ref_temp + stuck_min_drop:
                    LOGGER.warning(
                        "Stuck-underheat %s: за %d сек комната не нагрелась "
                        "(%.1f → %.1f) при ошибке %.2f — переотправка уставки",
                        self.entry.entry_id,
                        stuck_seconds,
                        ref_temp,
                        t_room,
                        e_heat,
                    )
                    self.last_action = "stuck_underheat_resend"
                    self._force_next_control = True
                    await self._set_valve_switch(True)
                # сброс трекинга: если комната растёт — перезапустится на след. тике
                self._stuck_cold_active = False
                self._stuck_cold_ref_temp = None
                self._stuck_cold_ref_time = None
            return t_trv, False

        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0
        self._stuck_cold_active = False
        self._stuck_cold_ref_temp = None
        self._stuck_cold_ref_time = None
        return t_trv, False

    # -------------------------
    # mode handlers (ИСПРАВЛЕННЫЕ)
    # -------------------------
    async def _handle_hvac_off(self, inp: Inputs):
        self._cancel_boost()

        # ШАГ 1: минимальная уставка для надёжного закрытия клапана
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        t_trv = _round_step(trv_min, step_min)
        await self._set_trv_temperature(inp.climate_entity, t_trv)

        # ШАГ 2: клапан закрыть через переключатель (если настроен)
        await self._set_valve_switch(False, force=True)

        # ШАГ 3: режим OFF на устройстве
        try:
            await self._set_trv_hvac_mode(inp.climate_entity, HVACMode.OFF)
        except Exception as e:
            LOGGER.warning("set_hvac_mode:off failed for %s: %s", inp.climate_entity, e)
        self.last_action = "hvac_off_valve_closed"

        self._stuck_bias = 0.0
        self._reset_stability_tracking()

    async def _align_window_offset(self, inp: Inputs) -> None:
        """Открытое окно — обычный контур, но свой offset.

        Раньше тик здесь обрывался: TRV на минимум и клапан закрыт.
        При окне на полсуток комната остывала при цели 23. Теперь греем
        и учим offset_open; закрыли — возвращаем offset_closed.
        """
        want = "open" if inp.window_open else "closed"
        have = self.storage.get_window_offset_regime(self.entry.entry_id)
        if have == want:
            return
        parked_key = "offset_open" if want == "open" else "offset_closed"
        live = self.storage.get_offset(self.entry.entry_id)
        parked = self.storage.get_parked_offset(self.entry.entry_id, parked_key)
        new_live, leave = _window_regime_offset(live, parked)
        leave_key = "offset_closed" if want == "open" else "offset_open"
        await self.storage.commit_window_regime(
            self.entry.entry_id,
            regime=want,
            live=new_live,
            parked_key=leave_key,
            parked_value=leave,
            reason=f"window_regime_{want}",
        )
        if abs(new_live - live) >= 0.01:
            self._pending_offset_delta = 0.0
            self._last_offset_update = inp.now_mono
        LOGGER.info(
            "Window regime %s: offset %.2f → %.2f (parked %.2f)",
            want,
            live,
            new_live,
            leave,
        )

    async def _maybe_handle_cold_start(self, inp: Inputs) -> None:
        """Большой недогрев (18→23): рывок TRV=max, ориентир — local TRV.

        Комната остаётся главным контуром; local только говорит «тепло пошло».
        Если батарея уже горячая (local ≫ room) — рывок не нужен.
        """
        if self.boost_active:
            return
        e = float(inp.t_effective) - float(inp.t_room)
        local = self._read_trv_local_temp(inp.climate_entity)
        if not _should_cold_start_jerk(
            e,
            cold_error=COLD_START_ERROR,
            t_room=inp.t_room,
            t_local=local,
            heat_margin=HEAT_FLOW_LOCAL_MARGIN,
            at_trv_max=self._command_at_max(inp.climate_entity),
        ):
            return
        if (
            self._last_cold_start_mono is not None
            and (inp.now_mono - self._last_cold_start_mono) < COLD_START_RETRY_SEC
        ):
            return

        # Пол offset: после рывка клапан не должен закрыться на старом −offset
        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        floor_offset = _clamp(
            (inp.t_room + TARGET_STEP_VALVE_MARGIN) - float(inp.t_effective),
            MIN_OFFSET,
            MAX_OFFSET,
        )
        if offset < floor_offset - 1e-9:
            await self.storage.set_offset(
                self.entry.entry_id, floor_offset, reason="cold_start_jerk"
            )
            self._pending_offset_delta = 0.0
            self._last_offset_update = inp.now_mono

        self._cold_start_boost = True
        self._last_cold_start_mono = inp.now_mono
        self.last_action = "cold_start_jerk"
        await self.start_boost(int(COLD_START_BOOST_SEC), trigger=False)
        LOGGER.warning(
            "Cold-start jerk %ds: room=%.1f target=%.1f local=%s e=%.2f",
            int(COLD_START_BOOST_SEC),
            inp.t_room,
            inp.t_effective,
            f"{local:.1f}" if local is not None else "?",
            e,
        )

    async def _handle_boost(self, inp: Inputs) -> bool:
        if not self.boost_active or inp.now_mono >= self.boost_until:
            return False

        e = float(inp.t_effective) - float(inp.t_room)
        local = self._read_trv_local_temp(inp.climate_entity)
        # Холодный старт: тепло подтверждено local И отрыв уже не катастрофа
        # → рано отдать управление комнатному контуру (не ждать весь таймер).
        if self._cold_start_boost and _trv_heat_flowing(
            inp.t_room, local, margin=HEAT_FLOW_LOCAL_MARGIN
        ) and e < COLD_START_HANDOFF_ERROR:
            self._cancel_boost()
            self.last_action = "cold_start_handoff"
            LOGGER.info(
                "Cold-start handoff: room=%.1f local=%s e=%.2f → active_control",
                inp.t_room,
                f"{local:.1f}" if local is not None else "?",
                e,
            )
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

        # Boost — клапан открыть
        await self._set_valve_switch(True, force=True)

        if self._cold_start_boost:
            self.last_action = "cold_start_jerk"
        elif self._arrival_boost:
            self.last_action = "arrival_warmup"
        elif self._schedule_boost:
            self.last_action = "schedule_boost"
        else:
            self.last_action = "boost"
        return True

    async def _maybe_handle_arrival(self, inp: Inputs) -> None:
        """Приход домой (person/активность): снять эко-эффект прогревом батарей.

        Предпочтительнее жёстких часов: ``person.*`` + свет/чайник.
        Первый тик после старта не триггерит (нет ложного «прихода»).
        Логирование приходов — всегда на фронте; boost — с кулдауном и
        только при недогреве (motion кухни иначе спамит arrival_warmup).
        """
        present = bool(self.ff.is_present())
        prev = self._prev_present
        self._prev_present = present
        if prev is None:
            return
        if not (present and not prev):
            return
        # Учим график приходов (утро/вечер) → потом предпрогрев за lead мин
        try:
            from homeassistant.util import dt as dt_util

            now_local = dt_util.now()
        except Exception:
            from datetime import datetime as _dt

            now_local = _dt.now().astimezone()
        minutes = now_local.hour * 60 + now_local.minute
        slot = _arrival_slot_kind(minutes)
        if slot:
            await self.storage.append_arrival(
                self.entry.entry_id,
                weekday=int(now_local.weekday()),
                minutes=minutes,
                slot=slot,
            )
            LOGGER.info(
                "Occupancy arrival logged: weekday=%s slot=%s %02d:%02d",
                now_local.weekday(),
                slot,
                now_local.hour,
                now_local.minute,
            )
        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        e = float(inp.t_effective) - float(inp.t_room)
        if not _should_arrival_warmup(
            present=present,
            prev_present=prev,
            boost_active=self.boost_active,
            error=e,
            deadband=deadband,
            now_mono=inp.now_mono,
            last_arrival_boost_mono=self._last_arrival_boost_mono,
            cooldown_sec=float(ARRIVAL_WARMUP_COOLDOWN_SEC),
        ):
            return
        # Поднять offset-пол, чтобы после boost клапан не закрылся
        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        floor_offset = _clamp(
            (inp.t_room + TARGET_STEP_VALVE_MARGIN) - float(inp.t_effective),
            MIN_OFFSET,
            MAX_OFFSET,
        )
        if offset < floor_offset - 1e-9:
            await self.storage.set_offset(
                self.entry.entry_id, floor_offset, reason="arrival_warmup"
            )
            self._pending_offset_delta = 0.0
            self._last_offset_update = inp.now_mono
        self._arrival_boost = True
        self._last_arrival_boost_mono = inp.now_mono
        self.last_action = "arrival_warmup"
        await self.start_boost(int(ARRIVAL_BOOST_SEC), trigger=False)
        LOGGER.warning(
            "Arrival warmup %ds (room=%.1f, e=%.2f, present via occupancy)",
            int(ARRIVAL_BOOST_SEC),
            inp.t_room,
            e,
        )

    async def _handle_deadband_hold(self, inp: Inputs, deadband: float) -> bool:
        e = inp.t_effective - inp.t_room
        
        # КРИТИЧЕСКИ ВАЖНО: если ошибка больше мёртвой зоны — не удерживаем!
        if abs(e) > deadband:
            return False

        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)

        baseline = _round_step(
            _clamp(inp.t_effective + offset, trv_min, trv_max), step_min
        )
        # Недогрев в deadband: не держать TRV ниже room+margin
        floor_trv = _underheat_trv_floor(
            inp.t_room, e, deadband, margin=UNDERHEAT_TRV_MARGIN
        )
        if floor_trv is not None and baseline < floor_trv:
            baseline = _round_step(
                _clamp(floor_trv, trv_min, trv_max), step_min
            )
        # Перелёт: не держать target+offset выше комнаты — иначе клапан
        # снова откроется, когда local TRV чуть остынет.
        ceiling_trv = _overshoot_trv_ceiling(
            inp.t_room, e, deadband, margin=OVERSHOOT_TRV_MARGIN
        )
        if ceiling_trv is not None and baseline > ceiling_trv:
            baseline = _round_step(
                _clamp(ceiling_trv, trv_min, trv_max), step_min
            )
        # Ранняя посадка: горячий local ИЛИ «долетим за N минут» + ещё лёгкий
        # недогрев → срезать раздутый offset до room+margin (approach_trv_ceiling).
        approach_capped = False
        room_rising = self._room_is_rising(inp)
        if not self.boost_active and not self.window_is_open:
            t_local = self._read_trv_local_temp(inp.climate_entity)
            local_rising = self._local_is_rising(inp, t_local)
            approach_ceil = _approach_trv_ceiling(
                inp.t_room,
                e,
                deadband,
                t_local,
                t_target=inp.t_effective,
                local_margin=HEAT_FLOW_LOCAL_MARGIN,
                approach_band_mult=APPROACH_BAND_MULT,
                approach_band_min=APPROACH_BAND_MIN,
                trv_margin=UNDERHEAT_TRV_MARGIN,
                heating_rate=self._heating_rate,
                minutes_per_degree=self._approach_mpd(),
                room_rising=room_rising,
                local_rising=local_rising,
                predict_max_min=APPROACH_PREDICT_MAX_MIN,
                rate_min=APPROACH_RATE_MIN,
            )
            if approach_ceil is not None and baseline > approach_ceil + 1e-9:
                baseline = _round_step(
                    _clamp(approach_ceil, trv_min, trv_max), step_min
                )
                approach_capped = True
        self.last_baseline = baseline

        target_changed = (
            self._last_room_target is not None
            and abs(inp.t_effective - self._last_room_target) > 1e-9
        )
        self._last_room_target = inp.t_effective

        if target_changed or self.last_set is None:
            self.last_target_trv = baseline
            if self.last_set is None or abs(baseline - self.last_set) >= (
                step_min - 1e-9
            ):
                await self._set_trv_temperature(inp.climate_entity, baseline)
                self.last_action = (
                    "deadband_rebase" if target_changed else "deadband_init"
                )
            self._reset_stability_tracking()
            return True

        # PID в удержании не вызывается — сбрасываем, чтобы интеграл не «висел»
        self._reset_pid()

        # Если hold держит TRV ниже пола недогрева — подтянуть
        if (
            floor_trv is not None
            and self.last_set is not None
            and self.last_set < baseline - 1e-9
        ):
            await self._set_trv_temperature(inp.climate_entity, baseline)
            self.last_action = "deadband_rebase"
            self.last_target_trv = baseline
            await self._set_valve_switch(True)
            return True

        # Ранняя посадка в hold: уставка ещё высокая, батарея горячая —
        # сразу к потолку (не ждать перелёта / cooldown) и подтянуть offset.
        if approach_capped:
            await self._apply_approach_offset(inp, room_rising)
        if (
            approach_capped
            and self.last_set is not None
            and self.last_set > baseline + 1e-9
        ):
            await self._set_trv_temperature(inp.climate_entity, baseline)
            self.last_action = "approach_close"
            self.last_target_trv = baseline
            await self._set_valve_switch(False)
            return True

        # Инерция: недогрев → открыть; перелёт цели → закрыть (остаток тепла
        # ещё догреет) и опустить уставку к baseline (с потолком закрытия).
        demand = _valve_heat_demand(e, deadband)
        if demand is True:
            await self._set_valve_switch(True)
        elif demand is False:
            await self._set_valve_switch(False)
            if self.last_set is not None and self.last_set > baseline + 1e-9:
                # При явном перелёте сразу к потолку (не по step_min/тик):
                # иначе 25→23 за 4 cooldown при уже горячей батарее.
                if ceiling_trv is not None:
                    new_set = baseline
                    action = "overshoot_close"
                else:
                    new_set = _round_step(
                        max(baseline, self.last_set - step_min), step_min
                    )
                    action = "deadband_step_down"
                if new_set <= self.last_set - (step_min - 1e-9):
                    await self._set_trv_temperature(inp.climate_entity, new_set)
                    self.last_action = action
                    self.last_target_trv = new_set
                    return True

        # Распад / trim / stable-learn не трогаем во время freeze после скачка вниз
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))
        if enable_learning and not self._is_learn_frozen(inp.now_mono):
            await self._handle_offset_decay(inp.now_mono, enable_learning, inp)
            # trim ДО stable: мягко уводим |offset| из 2…3, не дожидаясь 900с
            await self._handle_offset_trim_deadband(inp, deadband)
            await self._handle_stable_learning(inp, deadband)
        elif enable_learning:
            # freeze: только точка отсчёта decay, без изменения offset
            if self._last_offset_update is None:
                self._last_offset_update = inp.now_mono

        self.last_target_trv = self.last_set
        if self.last_action not in ("offset_trim", "stable_learn"):
            self.last_action = "hold"
        return True

    async def _handle_active_control(self, inp: Inputs):
        t_room = inp.t_room
        t_target = inp.t_effective
        e = t_target - t_room

        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        step_max = float(self.opt(CONF_STEP_MAX) or DEFAULT_STEP_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        learn_rate_fast = float(
            self.opt(CONF_LEARN_RATE_FAST) or DEFAULT_LEARN_RATE_FAST
        )
        min_offset_change = float(
            self.opt(CONF_MIN_OFFSET_CHANGE) or DEFAULT_MIN_OFFSET_CHANGE
        )
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        cooldown = float(self.opt(CONF_COOLDOWN_SEC) or DEFAULT_COOLDOWN_SEC)
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))

        heating_alpha = float(self.opt(CONF_HEATING_ALPHA) or DEFAULT_HEATING_ALPHA)
        overshoot_threshold = float(
            self.opt(CONF_OVERSHOOT_THRESHOLD) or DEFAULT_OVERSHOOT_THRESHOLD
        )

        stuck_enable = bool(self.opt(CONF_STUCK_ENABLE))
        stuck_seconds = int(self.opt(CONF_STUCK_SECONDS) or DEFAULT_STUCK_SECONDS)
        stuck_min_drop = float(self.opt(CONF_STUCK_MIN_DROP) or DEFAULT_STUCK_MIN_DROP)
        stuck_step = float(self.opt(CONF_STUCK_STEP) or DEFAULT_STUCK_STEP)

        # Клапан асимметрично: недогрев недопустим; закрытие при перелёте
        # цели (батарея всё равно остывает медленно).
        demand = _valve_heat_demand(e, deadband)
        if demand is True:
            await self._set_valve_switch(True)
        elif demand is False:
            await self._set_valve_switch(False)

        # TTT learning episode
        self._maybe_start_heat_episode(inp.now_mono, t_room, t_target, deadband)
        self._update_heat_episode(t_room)
        await self._maybe_finish_heat_episode(inp.now_mono, t_room, t_target, deadband)

        offset = _clamp(
            self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
        )

        # Ранняя посадка: потолок считаем ОДИН раз и ДО обучения — он же
        # признак «уставку придётся резать». Иначе active_learning тянет offset
        # ВВЕРХ (e > 0) в том же тике, где approach_trim тянет его ВНИЗ:
        # два писателя, двойной шаг за тик и осцилляция. Факт: спальня 04.11 —
        # offset +2.85 часами держал TRV 26 при room≈23 и local 24+.
        room_rising = self._room_is_rising(inp)
        approach_ceil = None
        if not self.boost_active and not self.window_is_open:
            t_local = self._read_trv_local_temp(inp.climate_entity)
            local_rising = self._local_is_rising(inp, t_local)
            approach_ceil = _approach_trv_ceiling(
                t_room,
                e,
                deadband,
                t_local,
                t_target=t_target,
                local_margin=HEAT_FLOW_LOCAL_MARGIN,
                approach_band_mult=APPROACH_BAND_MULT,
                approach_band_min=APPROACH_BAND_MIN,
                trv_margin=UNDERHEAT_TRV_MARGIN,
                heating_rate=self._heating_rate,
                minutes_per_degree=self._approach_mpd(),
                room_rising=room_rising,
                local_rising=local_rising,
                predict_max_min=APPROACH_PREDICT_MAX_MIN,
                rate_min=APPROACH_RATE_MIN,
            )
        landing_active = (
            approach_ceil is not None
            and (t_target + offset) > approach_ceil + 1e-9
        )

        # overshoot auto-tune (не во время freeze после скачка цели вниз —
        # иначе эко-«перегрев» 21°C при цели 18 копит overshoot и убивает rate).
        # Инерция: room ещё выше цели при уже закрытом TRV (overshoot_close)
        # не должна дальше душить learn_rate — иначе offset залипает на часы.
        learn_frozen = self._is_learn_frozen(inp.now_mono)
        still_heating = self._is_likely_heating(t_room)
        if (
            (not learn_frozen)
            and not inp.window_open
            and t_room > t_target + overshoot_threshold
            and still_heating
        ):
            self._last_overshoot_mono = inp.now_mono
            new_count = await self.storage.increment_overshoot_count(
                self.entry.entry_id
            )
            self._overshoot_count = new_count
            if self._overshoot_count > 3:
                self._learn_rate_slow = max(
                    LEARN_RATE_FLOOR,
                    self._learn_rate_slow * LEARN_RATE_AUTOTUNE_MULT,
                )
                LOGGER.info(
                    "Auto-tune: снижен learn_rate_slow до %.3f из-за перегрева",
                    self._learn_rate_slow,
                )
                self._overshoot_count = 0
                # персистим результат auto-tune (иначе терялся при reload);
                # base — настроенное значение: если пользователь его сменит,
                # auto-tune начнётся заново (восстановление в async_start)
                if hasattr(self.storage, "set_learn_rate_slow"):
                    await self.storage.set_learn_rate_slow(
                        self.entry.entry_id,
                        float(
                            self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW
                        ),
                        self._learn_rate_slow,
                    )
        elif not learn_frozen:
            # ВОССТАНОВЛЕНИЕ auto-tune. Раньше learn_rate_slow только снижался
            # (×0.9 за каждые 4 тика перегрева, пол 0.01) и обратно не
            # возвращался НИКОГДА — однонаправленная трещотка: overshoot_count
            # уходил за 2500, rate залипал на полу во всех комнатах, медленное
            # обучение фактически умирало (поправки ~0.005/тик). Теперь после
            # LEARN_RATE_RECOVERY_SEC без перегрева плавно возвращаем rate
            # к настроенной базе и обнуляем счётчик перегрева.
            base_rate = float(
                self.opt(CONF_LEARN_RATE_SLOW) or DEFAULT_LEARN_RATE_SLOW
            )
            if self._last_overshoot_mono is None:
                # первый «чистый» тик — только ставим точку отсчёта
                self._last_overshoot_mono = inp.now_mono
            elif (
                inp.now_mono - self._last_overshoot_mono
            ) >= LEARN_RATE_RECOVERY_SEC:
                self._last_overshoot_mono = inp.now_mono
                if self._overshoot_count > 0:
                    self._overshoot_count = 0
                    await self.storage.set_overshoot_count(self.entry.entry_id, 0)
                if self._learn_rate_slow < base_rate - 1e-9:
                    self._learn_rate_slow = min(
                        base_rate,
                        self._learn_rate_slow * LEARN_RATE_RECOVERY_MULT,
                    )
                    LOGGER.info(
                        "Auto-tune: learn_rate_slow восстановлен до %.3f "
                        "(нет перегрева %d сек)",
                        self._learn_rate_slow,
                        int(LEARN_RATE_RECOVERY_SEC),
                    )
                    if hasattr(self.storage, "set_learn_rate_slow"):
                        await self.storage.set_learn_rate_slow(
                            self.entry.entry_id, base_rate, self._learn_rate_slow
                        )

        # АКТИВНОЕ ОБУЧЕНИЕ ДЛЯ НАГРЕВА И ОСТЫВАНИЯ
        # Freeze после скачка цели вниз: не учиться на эко-«перегреве»
        if enable_learning and not learn_frozen:
            # ВЫХОД ИЗ НАСЫЩЕНИЯ: если offset ушёл глубоко в предел, а ошибка
            # тянет в обратную сторону — учимся БЫСТРОЙ скоростью всегда.
            # Раньше быстрая скорость включалась только при |e| > 2*deadband,
            # а при deadband < |e| <= 2*deadband поправка (learn_rate_slow*|e|)
            # была меньше min_offset_change и молча отбрасывалась — offset
            # замирал у -6 на ЧАСЫ: уставка TRV (target - 6 + PID) оставалась
            # ниже температуры комнаты, клапан стоял закрытым, хотя виртуальная
            # уставка была выше комнатной (спальня, ночь 19.10: 12 часов
            # без единого изменения offset при холодной комнате).
            # soft_against: |offset|>2 и ошибка явно «против» вне deadband.
            # Иначе (спальня +2.55 / e=-0.6 / tuned=0.01) шаг −0.006/тик,
            # а trim в hold недоступен → offset стоит часами.
            soft_against = (
                (offset >= OFFSET_TRIM_SOFT_TRIGGER and e < -deadband)
                or (offset <= -OFFSET_TRIM_SOFT_TRIGGER and e > deadband)
            )
            deep_against = (
                (offset <= -OFFSET_SATURATED_TRIGGER and e > 0)
                or (offset >= OFFSET_SATURATED_TRIGGER and e < 0)
                or soft_against
            )
            if abs(e) > deadband * 2 or deep_against:
                learn_rate = learn_rate_fast
            else:
                learn_rate = self._learn_rate_slow

            # Обучение только вне deadband. Trim 2<|offset|≤3 — в hold.
            adjustment = 0.0
            learn_direction = 0
            if abs(e) > deadband:
                learn_direction = 1 if e > 0 else -1
                adjustment = learn_direction * learn_rate * abs(e)

            # Уставка срезана посадкой ⇒ «недогрев» здесь искусственный (мы сами
            # закрыли клапан): не учить offset ВВЕРХ в том же тике, где
            # approach_trim учит его ВНИЗ. Вниз (e < 0) не блокируем — там
            # overshoot/trim и freeze после скачка цели.
            if landing_active and adjustment > 0.0:
                adjustment = 0.0
            # Окно опустило цель до эко: комната выше этой цели — не «перегрев
            # контура». Вниз offset не учим, иначе открытый режим уедет к −6.
            # Вверх, если стало холоднее эко, учим как обычно.
            if inp.window_open and adjustment < 0.0:
                adjustment = 0.0

            # ГВАРД «клапан без власти»: TRV открывается пропорционально
            # (уставка − local). Уставка уже выше local+margin и тепло НЕ
            # течёт (local ≈ room — котёл/циркуляция не дают) → учить offset
            # ВВЕРХ бессмысленно: батарея больше не даст, offset улетает к +6
            # и позже выстреливает перегревом (детская 02.11: 1.8→+6 за час
            # при мёртвой комнате 22.3). Симметрично: уставка ниже
            # local−margin → клапан уже закрыт, эко-«перегрев» иначе хоронит
            # offset к −6 и убивает утренний прогрев. Выход из насыщения
            # (deep_against) не страдает: при offset ±6 уставка далеко от
            # заблокированной зоны. local нет/битый → гвард молчит.
            if adjustment != 0.0:
                t_local = self._read_trv_local_temp(inp.climate_entity)
                # Желаемая уставка ЭТОГО тика без PID (при e>0 PID только
                # добавляет → это нижняя граница). last_set отстаёт на тик
                # (Zigbee) и затирается низким reported при mismatch, поэтому
                # берём «худшую» для направления: вверх — max, вниз — min.
                ref_set = _valve_ref_setpoint(
                    learn_direction,
                    self.last_set,
                    float(inp.t_effective) + offset,
                )
                if _valve_learning_blocked(
                    learn_direction,
                    ref_set,
                    t_local,
                    float(inp.t_room),
                    travel_margin=float(VALVE_TRAVEL_MARGIN),
                    heat_margin=float(HEAT_FLOW_LOCAL_MARGIN),
                ):
                    adjustment = 0.0
                    # Остаток накопленного в блокированную сторону обнуляем —
                    # иначе выстрелит позже, когда гвард отпустит
                    if learn_direction * self._pending_offset_delta > 0:
                        self._pending_offset_delta = 0.0
                    LOGGER.debug(
                        "Valve authority: обучение %s заблокировано "
                        "(set=%.1f, local=%.1f, room=%.1f, e=%.2f)",
                        "вверх" if learn_direction > 0 else "вниз",
                        ref_set,
                        t_local if t_local is not None else float("nan"),
                        inp.t_room,
                        e,
                    )

            # Ограничение скорости обучения: не более max_offset_step за тик
            # (раньше learn_rate_fast*|e| давал до ±2.5°C/тик и offset улетал в предел)
            max_offset_step = float(
                self.opt(CONF_MAX_OFFSET_STEP) or DEFAULT_MAX_OFFSET_STEP
            )
            adjustment = _clamp(adjustment, -max_offset_step, max_offset_step)

            # НАКОПЛЕНИЕ дробных поправок. Раньше поправка меньше
            # min_offset_change (0.1) молча отбрасывалась КАЖДЫЙ тик без
            # следа: медленное обучение 0.07*|e| работало только при
            # |e| > 1.4 °C, а после auto-tune (rate → 0.01) не работало
            # ВООБЩЕ — обучение выглядело «очень долгим» (фактически стояло).
            # Теперь малые поправки копятся и применяются одним пакетом;
            # накопленное тоже ограничено max_offset_step — разовая запись
            # не может изменить offset больше чем на него (анти-взлёт,
            # инвариант раздела 4 правил проекта).
            if adjustment != 0.0:
                self._pending_offset_delta = _clamp(
                    self._pending_offset_delta + adjustment,
                    -max_offset_step,
                    max_offset_step,
                )

            if abs(self._pending_offset_delta) >= min_offset_change:
                new_offset = _clamp(
                    offset + self._pending_offset_delta, MIN_OFFSET, MAX_OFFSET
                )
                applied = new_offset - offset
                if abs(applied) >= min_offset_change:
                    await self.storage.set_offset(
                        self.entry.entry_id, new_offset, reason="active_learning"
                    )
                    self._last_offset_update = inp.now_mono
                    LOGGER.debug(
                        "Offset adjusted: %.2f → %.2f (error=%.2f, pending=%.3f)",
                        offset,
                        new_offset,
                        e,
                        self._pending_offset_delta,
                    )
                    offset = new_offset  # Обновляем для дальнейших расчётов
                    self._pending_offset_delta -= applied
                else:
                    # offset упёрся в предел — копиться дальше нечему,
                    # иначе остаток выстрелил бы позже в другую сторону
                    self._pending_offset_delta = 0.0

        # PID coefficients из опций (могут меняться во время работы)
        self.pid.kp = float(self.opt(CONF_PID_KP) or DEFAULT_PID_KP)
        self.pid.ki = float(self.opt(CONF_PID_KI) or DEFAULT_PID_KI)
        self.pid.kd = float(self.opt(CONF_PID_KD) or DEFAULT_PID_KD)
        # correction (PID): i_limit = step_max — защита от windup интеграла
        correction = self.pid.update(
            e, t_target, inp.now_mono, step_max, i_limit=step_max
        )

        # МЯГКАЯ ПОСАДКА (только при нагреве): в полосе от deadband до
        # deadband + ease_span плавно гасим коррекцию PID к полу
        # SOFT_LANDING_FLOOR, чтобы у границы мёртвой зоны уставка уже
        # стояла у baseline и клапан закрывался до перегрева по инерции.
        #
        # Прежние время-зависимые механизмы (TTT-фактор, overshoot-фактор и
        # отсечка по heating_rate) были МЁРТВЫМ КОДОМ: их пороги срабатывания
        # (e < 0.05..0.35 °C при реальных heating_rate 0.013..0.035 °C/мин)
        # лежали НИЖЕ deadband, при котором active_control вообще не вызывается.
        # Из-за этого система входила в мёртвую зону с полной коррекцией
        # +step_max и перегревала по инерции (overshoot_count 19/19).
        # Подробнее: plans/precision-improvements.md (P0-1).
        correction = _apply_soft_landing(
            correction,
            e,
            deadband,
            floor=SOFT_LANDING_FLOOR,
            span_mult=SOFT_LANDING_SPAN_MULT,
            span_min=SOFT_LANDING_SPAN_MIN,
        )

        t_trv = _round_step(t_target + offset + correction, step_min)

        # Анти-недогрев: при e > deadband уставка TRV не ниже room+margin,
        # иначе физический клапан закрыт при «нужно греть» (offset у −3…−6).
        floor_trv = _underheat_trv_floor(
            t_room, e, deadband, margin=UNDERHEAT_TRV_MARGIN
        )
        if floor_trv is not None and t_trv < floor_trv:
            t_trv = _round_step(floor_trv, step_min)

        # Анти-перелёт: при комнате выше цели TRV не выше room−margin,
        # иначе idle + target+offset снова открывает клапан (спальня).
        ceiling_trv = _overshoot_trv_ceiling(
            t_room, e, deadband, margin=OVERSHOOT_TRV_MARGIN
        )
        overshoot_capped = False
        if ceiling_trv is not None and t_trv > ceiling_trv:
            t_trv = _round_step(ceiling_trv, step_min)
            overshoot_capped = True

        # Ранняя посадка (до перелёта): горячий local ИЛИ прогноз «долетим за
        # N минут» + e в полосе soft-landing → TRV ≤ room+underheat_margin,
        # иначе offset держит 26 при room 23. Потолок посчитан выше (до обучения).
        approach_capped = False
        if approach_ceil is not None and t_trv > approach_ceil + 1e-9:
            t_trv = _round_step(approach_ceil, step_min)
            approach_capped = True
            await self._apply_approach_offset(inp, room_rising)
            # Остаточное тепло догреет — внешний клапан закрыть, если есть
            await self._set_valve_switch(False)

        # stuck logic
        if stuck_enable and (not self.window_is_open) and (not self.boost_active):
            t_trv, _ = await self._handle_stuck_detection(
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
                e_demand=float(inp.t_target) - t_room,
            )

        t_trv = _clamp(t_trv, trv_min, trv_max)
        self.last_target_trv = t_trv

        # Скорость нагрева ДО anti-spam: при skipped_no_change (типичный
        # тик при греющем TRV) раньше rate не обновлялся вообще.
        if (
            e > deadband
            and not self.window_is_open
            and not self.boost_active
            and self._is_likely_heating(t_room)
        ):
            await self._update_heating_rate(t_room, inp.now_mono, heating_alpha)

        # anti spam (перелёт / ранняя посадка: не ждать cooldown)
        urgent_cap = overshoot_capped or approach_capped
        if self.last_set is not None:
            if abs(t_trv - self.last_set) < (step_min - 1e-9):
                self.last_action = "skipped_no_change"
                return
            if (
                inp.now_mono - self.last_change
            ) < cooldown and not self._force_next_control and not urgent_cap:
                self.last_action = "cooldown"
                return

        # анти-дребезг (min_on/min_off): не менять направление уставки слишком часто
        if (
            self.last_set is not None
            and not self._force_next_control
            and not urgent_cap
        ):
            desired = t_trv - self.last_set
            if abs(desired) >= (step_min - 1e-9):
                direction = 1 if desired > 0 else -1
                if direction != self._last_set_direction and self._last_set_direction != 0:
                    elapsed = inp.now_mono - self._last_set_direction_time
                    min_sec = (
                        float(self.opt(CONF_MIN_OFF_SEC) or DEFAULT_MIN_OFF_SEC)
                        if direction > 0
                        else float(self.opt(CONF_MIN_ON_SEC) or DEFAULT_MIN_ON_SEC)
                    )
                    if elapsed < min_sec:
                        self.last_action = "anti_chatter"
                        return

        success = await self._set_trv_temperature(inp.climate_entity, t_trv)
        if success:
            if overshoot_capped:
                self.last_action = "overshoot_close"
            elif approach_capped:
                self.last_action = "approach_close"
            else:
                self.last_action = "set_temperature"

        # Распад после активного контроля (не во время freeze после скачка вниз)
        if enable_learning and not self._is_learn_frozen(inp.now_mono):
            await self._handle_offset_decay(inp.now_mono, enable_learning, inp)

    # -------------------------
    # main tick (ПОЛНОСТЬЮ ПЕРЕПИСАННЫЙ С ЗАЩИТОЙ)
    # -------------------------
    async def _tick(self, _):
        try:
            now_mono = self.hass.loop.time()

            inp = await self._read_inputs(now_mono)
            if not inp:
                # КРИТИЧЕСКИ ВАЖНО: немедленно выйти из состояния "init" при недоступных сенсорах
                if self.last_action == "init":
                    self.last_action = "waiting_sensors"
                    LOGGER.info(
                        "Controller %s transitioning from 'init' to 'waiting_sensors' (attempt #%d)",
                        self.entry.entry_id,
                        self._startup_attempts,
                    )
                    # Запускаем активный опрос датчиков
                    self._start_sensor_retry()
                    # # Запускаем слушатель появления датчиков
                    # self._ensure_sensor_listener()
                
                self._notify()
                return

            # Сенсоры доступны — останавливаем активный опрос
            self._stop_sensor_retry()

            # Сенсоры доступны — выходим из состояния инициализации
            if self.last_action in ("init", "waiting_sensors", "init_error_retry"):
                previous_state = self.last_action
                self.last_action = "operational"
                LOGGER.info(
                    "Controller %s initialized successfully (previous state: '%s', room temp: %.1f°C)",
                    self.entry.entry_id,
                    previous_state,
                    inp.t_room,
                )

            e = inp.t_effective - inp.t_room
            self.last_error = round(e, 3)

            # Бюджет обучения: offset ДО писателей этого тика. Суммарный шаг
            # за тик не должен превышать max_offset_step (инвариант 3) —
            # active_learning, deadband trim и approach_trim живут в одном тике.
            self._tick_offset_snapshot = _clamp(
                self.storage.get_offset(self.entry.entry_id), MIN_OFFSET, MAX_OFFSET
            )

            # Диагностика «источник не даёт тепло» (до обработчиков,
            # чтобы состояние жило и в boost/окне/Off)
            try:
                self._update_heat_delivery(
                    inp, float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
                )
            except Exception:
                # диагностика не должна ломать тик (инвариант 1)
                self.heat_delivery = "unknown"

            # Верификация уставки: фактическое значение на TRV vs last_set.
            # Раньше потерянная команда (Zigbee) навсегда блокировала переотправку.
            self.trv_reported_setpoint = inp.trv_reported_setpoint
            if (
                inp.trv_reported_setpoint is not None
                and self.last_set is not None
                and abs(inp.trv_reported_setpoint - self.last_set) > 0.5
            ):
                LOGGER.warning(
                    "TRV %s: уставка на устройстве %.1f ≠ last_set %.1f — переотправка",
                    inp.climate_entity,
                    inp.trv_reported_setpoint,
                    self.last_set,
                )
                self.trv_setpoint_sync = "mismatch"
                self.last_set = inp.trv_reported_setpoint
                self._force_next_control = True
            elif inp.trv_reported_setpoint is not None:
                self.trv_setpoint_sync = "ok"

            # Valve exercise (обслуживание клапана)
            exercise_days = int(self.opt(CONF_VALVE_EXERCISE_DAYS) or 0)
            if exercise_days > 0:
                if self._valve_exercise_active:
                    if inp.now_mono < self._valve_exercise_until:
                        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
                        await self._set_trv_temperature(inp.climate_entity, trv_max)
                        self.last_action = "valve_exercise"
                        await self._end_tick(inp, now_mono)
                        return
                    self._cancel_valve_exercise()
                    await self.storage.set_valve_exercise(
                        self.entry.entry_id, time.time()
                    )
                elif (
                    inp.hvac_mode != HVACMode.OFF.value
                    and not inp.window_open
                    and not self.boost_active
                ):
                    last_ex = self.storage.get_valve_exercise(self.entry.entry_id)
                    # epoch-время: монотонные часы обнулялись при рестарте HA,
                    # и автопрокрутка откладывалась на новые exercise_days аптайма
                    if time.time() - last_ex >= exercise_days * 86400:
                        await self._start_valve_exercise(inp)
                        await self._end_tick(inp, now_mono)
                        return

            current_mode = inp.hvac_mode
            
            # Обработка переходов режимов: открыть клапан при переходе в HEAT
            if (self._prev_hvac_mode_config == HVACMode.OFF.value and
                current_mode == HVACMode.HEAT.value):
                await self._set_valve_switch(True, force=True)

            self._prev_hvac_mode_config = current_mode

            if inp.hvac_mode == HVACMode.OFF.value:
                await self._handle_hvac_off(inp)
                await self._end_tick(inp, now_mono)
                return

            await self._set_trv_hvac_mode(inp.climate_entity, HVACMode.HEAT)

            # Окно не обрывает тик: цель держим и при открытом окне.
            await self._align_window_offset(inp)

            # Скачок цели по расписанию (до boost): авто-прогрев / freeze обучения
            await self._maybe_handle_target_step(inp)
            # Приход домой по person/свет/чайник (предпочтительнее часов)
            await self._maybe_handle_arrival(inp)
            # Большой недогрев (18→23): рывок + контроль local TRV
            await self._maybe_handle_cold_start(inp)

            if await self._handle_boost(inp):
                await self._end_tick(inp, now_mono)
                return

            deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
            
            # 🔴 КРИТИЧЕСКАЯ ЗАЩИТА: не входить в удержание если ошибка > deadband
            if abs(e) > deadband:
                # Пропускаем мёртвую зону — нужен активный контроль
                await self._handle_active_control(inp)
                await self._end_tick(inp, now_mono)
                return

            # Только если ошибка действительно в пределах мёртвой зоны
            if await self._handle_deadband_hold(inp, deadband):
                await self._end_tick(inp, now_mono)
                return

            # Если не в удержании — активный контроль
            await self._handle_active_control(inp)
            await self._end_tick(inp, now_mono)

        except Exception as e:
            # КРИТИЧЕСКИ ВАЖНО: никогда не останавливать контроллер из-за ошибки в тике!
            if self.last_action == "init":
                self.last_action = "init_error_retry"
                LOGGER.error(
                    "Controller %s failed during initialization (state changed to 'init_error_retry'). Error: %s",
                    self.entry.entry_id,
                    e,
                )
            else:
                LOGGER.exception(
                    "Unexpected error in _tick for %s (current state: '%s'). Controller will continue on next interval: %s",
                    self.entry.entry_id,
                    self.last_action,
                    e,
                )
            self._notify()