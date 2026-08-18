"""Feedforward-компенсация: эко-режим (присутствие) и погода.

Вычисляет «эффективную» целевую температуру = базовая цель + эко-смещение
+ погодная компенсация. Используется контроллером для принятия решений
и расчёта уставки.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ECO_ENABLE,
    CONF_ECO_OFFSET,
    CONF_OUTDOOR_SENSOR,
    CONF_PREDICTIVE_FACTOR,
    CONF_PRESENCE_ENTITY,
    CONF_WEATHER_BASE_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_WEATHER_MAX_COMP,
    DEFAULT_ECO_ENABLE,
    DEFAULT_PREDICTIVE_FACTOR,
    DEFAULT_WEATHER_BASE_TEMP,
    DEFAULT_WEATHER_MAX_COMP,
)
from .helpers import clamp, normalize_entity_list, to_float

_PRESENT_STATES = ("home", "on", "true", "present", "open", "1", "yes")


class Feedforward:
    """Читает состояние HA и вычисляет эко/погодную коррекцию цели."""

    def __init__(self, hass: HomeAssistant, opt: Callable[[str], Any]):
        self.hass = hass
        self._opt = opt  # callable(key) -> значение из options/data/defaults

    # ---------- присутствие / эко ----------
    def is_present(self) -> bool:
        """Есть ли люди дома. Без датчиков считаем, что люди дома."""
        ents = normalize_entity_list(self._opt(CONF_PRESENCE_ENTITY))
        if not ents:
            return True
        for ent in ents:
            st = self.hass.states.get(ent)
            if st and str(st.state).lower() in _PRESENT_STATES:
                return True
        return False

    def eco_delta(self) -> float:
        """Смещение цели при отсутствии людей (эко-режим)."""
        if not bool(self._opt(CONF_ECO_ENABLE)):
            return 0.0
        if self.is_present():
            return 0.0
        return float(self._opt(CONF_ECO_OFFSET) or 0.0)

    # ---------- погода ----------
    def get_outdoor_temp(self) -> Optional[float]:
        """Наружная температура: датчик → weather → прогноз."""
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
        """Компенсация цели по холоду: чем холоднее — тем агрессивнее нагрев."""
        t_out = self.get_outdoor_temp()
        if t_out is None:
            return 0.0
        base = float(self._opt(CONF_WEATHER_BASE_TEMP) or DEFAULT_WEATHER_BASE_TEMP)
        gain = float(self._opt(CONF_PREDICTIVE_FACTOR) or DEFAULT_PREDICTIVE_FACTOR)
        max_comp = float(self._opt(CONF_WEATHER_MAX_COMP) or DEFAULT_WEATHER_MAX_COMP)
        if t_out >= base:
            return 0.0
        return clamp(gain * (base - t_out), 0.0, max_comp)

    # ---------- итоговая цель ----------
    def effective_target(self, t_target: float, hvac_mode: str) -> float:
        """Итоговая цель = базовая + эко + погода (не в режиме OFF)."""
        t_eff = t_target
        if hvac_mode != HVACMode.OFF.value:
            t_eff += self.eco_delta()
            t_eff += self.weather_delta()
        return t_eff