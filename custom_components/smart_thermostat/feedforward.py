"""Feedforward: occupancy, выученный предпрогрев, опциональные часы, погода."""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ECO_ENABLE,
    CONF_ECO_OFFSET,
    CONF_LEARNED_PREHEAT_ENABLE,
    CONF_LEARNED_PREHEAT_LEAD_MIN,
    CONF_OCCUPANCY_ACTIVITY,
    CONF_OCCUPANCY_HOLD_MIN,
    CONF_OUTDOOR_SENSOR,
    CONF_PREDICTIVE_FACTOR,
    CONF_PRESENCE_ENTITY,
    CONF_PREHEAT_EVENING_READY,
    CONF_PREHEAT_LEAD_MIN,
    CONF_PREHEAT_MORNING_READY,
    CONF_PREHEAT_MORNING_READY_WEEKEND,
    CONF_PRESET_COMFORT_TEMP,
    CONF_WEATHER_BASE_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_MAX_COMP,
    CONF_WORKDAY_SENSOR,
    DEFAULT_LEARNED_PREHEAT_ENABLE,
    DEFAULT_LEARNED_PREHEAT_LEAD_MIN,
    DEFAULT_OCCUPANCY_HOLD_MIN,
    DEFAULT_PREHEAT_EVENING_READY,
    DEFAULT_PREHEAT_LEAD_MIN,
    DEFAULT_PREHEAT_MORNING_READY,
    DEFAULT_PREHEAT_MORNING_READY_WEEKEND,
    DEFAULT_PRESET_COMFORT_TEMP,
    DEFAULT_PREDICTIVE_FACTOR,
    DEFAULT_WEATHER_BASE_TEMP,
    DEFAULT_WEATHER_MAX_COMP,
    LEARNED_PREHEAT_MIN_SAMPLES,
)
from .helpers import (
    active_preheat_slot,
    clamp,
    in_learned_preheat_window,
    merge_occupancy,
    normalize_entity_list,
    predict_arrival_minutes,
    state_means_activity,
    state_means_home,
    to_float,
)

_WORKDAY_STATES = ("on", "true", "1", "workday", "home")


class Feedforward:
    """Occupancy + эко + выученный график приходов + погода."""

    def __init__(
        self,
        hass: HomeAssistant,
        opt: Callable[[str], Any],
        storage: Any = None,
        entry_id: Optional[str] = None,
    ):
        self.hass = hass
        self._opt = opt
        self.storage = storage
        self.entry_id = entry_id
        self._activity_hold_until: float = 0.0

    def _opt_or(self, key: str, default: Any) -> Any:
        val = self._opt(key)
        return default if val is None else val

    def _person_entities(self) -> list[str]:
        return normalize_entity_list(self._opt(CONF_PRESENCE_ENTITY))

    def _activity_entities(self) -> list[str]:
        return normalize_entity_list(self._opt(CONF_OCCUPANCY_ACTIVITY))

    def any_person_home(self) -> bool:
        for ent in self._person_entities():
            st = self.hass.states.get(ent)
            if st and state_means_home(st.state):
                return True
        return False

    def any_activity_on(self) -> bool:
        for ent in self._activity_entities():
            st = self.hass.states.get(ent)
            if st and state_means_activity(st.state):
                return True
        return False

    def is_present(self) -> bool:
        persons = self._person_entities()
        activities = self._activity_entities()
        activity_on = self.any_activity_on() if activities else False
        if activity_on:
            hold_min = int(
                self._opt_or(CONF_OCCUPANCY_HOLD_MIN, DEFAULT_OCCUPANCY_HOLD_MIN)
            )
            self._activity_hold_until = time.time() + max(0, hold_min) * 60.0
        hold_active = time.time() < self._activity_hold_until
        return merge_occupancy(
            person_home=self.any_person_home() if persons else None,
            activity_on=activity_on,
            activity_hold_active=hold_active,
            has_person_sensors=bool(persons),
            has_activity_sensors=bool(activities),
        )

    def is_workday(self) -> bool | None:
        ent = self._opt(CONF_WORKDAY_SENSOR)
        if not ent:
            return None
        if isinstance(ent, (list, tuple)):
            ent = ent[0] if ent else None
        if not ent:
            return None
        st = self.hass.states.get(str(ent))
        if st is None or st.state in ("unavailable", "unknown"):
            return None
        return str(st.state).lower() in _WORKDAY_STATES

    def clock_preheat_slot(self) -> str | None:
        """Ручные часы (advanced) — только если пользователь задал времена."""
        return active_preheat_slot(
            dt_util.now(),
            self._opt_or(CONF_PREHEAT_MORNING_READY, DEFAULT_PREHEAT_MORNING_READY),
            self._opt_or(CONF_PREHEAT_EVENING_READY, DEFAULT_PREHEAT_EVENING_READY),
            int(self._opt_or(CONF_PREHEAT_LEAD_MIN, DEFAULT_PREHEAT_LEAD_MIN)),
            is_workday=self.is_workday(),
            morning_ready_weekend=self._opt_or(
                CONF_PREHEAT_MORNING_READY_WEEKEND,
                DEFAULT_PREHEAT_MORNING_READY_WEEKEND,
            ),
            evening_on_weekend=False,
        )

    def learned_preheat_slot(self) -> str | None:
        """Предпрогрев по выученным приходам (person/чайника), не по жёстким часам.

        Нужно ≥ LEARNED_PREHEAT_MIN_SAMPLES приходов в слоте; lead —
        ``learned_preheat_lead_min`` (30 / 45 / 60…).
        """
        if not bool(
            self._opt_or(CONF_LEARNED_PREHEAT_ENABLE, DEFAULT_LEARNED_PREHEAT_ENABLE)
        ):
            return None
        if self.is_present():
            return None
        if self.storage is None or not self.entry_id:
            return None
        hist = self.storage.get_arrival_history(self.entry_id)
        if not hist:
            return None
        now = dt_util.now()
        now_m = now.hour * 60 + now.minute
        wd = int(now.weekday())
        lead = int(
            self._opt_or(
                CONF_LEARNED_PREHEAT_LEAD_MIN, DEFAULT_LEARNED_PREHEAT_LEAD_MIN
            )
        )
        for slot in ("morning", "evening"):
            typical = predict_arrival_minutes(
                hist, wd, slot, min_samples=LEARNED_PREHEAT_MIN_SAMPLES
            )
            if typical is None:
                continue
            if in_learned_preheat_window(now_m, typical, lead):
                return slot
        return None

    def preheat_slot(self) -> str | None:
        """Сначала выученный график, иначе опциональные ручные часы."""
        return self.learned_preheat_slot() or self.clock_preheat_slot()

    def eco_delta(self) -> float:
        if not bool(self._opt(CONF_ECO_ENABLE)):
            return 0.0
        if self.preheat_slot() is not None:
            return 0.0
        if self.is_present():
            return 0.0
        return float(self._opt(CONF_ECO_OFFSET) or 0.0)

    def get_outdoor_temp(self) -> Optional[float]:
        sensor = self._opt(CONF_OUTDOOR_SENSOR)
        if sensor:
            st = self.hass.states.get(sensor)
            t = to_float(st.state if st else None)
            if t is not None:
                return t
        we = self._opt(CONF_WEATHER_ENTITY)
        if we:
            st = self.hass.states.get(we)
            if st:
                t = to_float(st.attributes.get("temperature"))
                if t is not None:
                    return t
                forecast = st.attributes.get("forecast")
                if isinstance(forecast, list) and forecast:
                    t = to_float(forecast[0].get("temperature"))
                    if t is not None:
                        return t
        return None

    def weather_delta(self) -> float:
        t_out = self.get_outdoor_temp()
        if t_out is None:
            return 0.0
        base = float(self._opt(CONF_WEATHER_BASE_TEMP) or DEFAULT_WEATHER_BASE_TEMP)
        gain = float(self._opt(CONF_PREDICTIVE_FACTOR) or DEFAULT_PREDICTIVE_FACTOR)
        max_comp = float(self._opt(CONF_WEATHER_MAX_COMP) or DEFAULT_WEATHER_MAX_COMP)
        if t_out >= base:
            return 0.0
        return clamp(gain * (base - t_out), 0.0, max_comp)

    def effective_target(
        self, t_target: float, hvac_mode: str, skip_weather: bool = False
    ) -> float:
        t_eff = t_target
        if hvac_mode != HVACMode.OFF.value:
            t_eff += self.eco_delta()
            if not skip_weather:
                t_eff += self.weather_delta()
            if self.preheat_slot() is not None:
                comfort = float(
                    self._opt_or(CONF_PRESET_COMFORT_TEMP, DEFAULT_PRESET_COMFORT_TEMP)
                )
                if t_eff < comfort:
                    t_eff = comfort
        return t_eff
