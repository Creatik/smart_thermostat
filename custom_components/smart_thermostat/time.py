"""Два времени на странице устройства: комфорт днём и сон.

У каждой комнаты свой набор. «Сон с» — когда цель падает до сна,
его ставят за пару часов до отхода: комната остывает медленно.
Автоматизация читает те же помощники.
"""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_CLIMATE, DOMAIN
from .helpers import thermostat_device_label

_LOGGER = logging.getLogger(__name__)

# Климат → префикс помощников. Незнакомая запись не делит чужое время.
_ROOM_PREFIX = {
    "climate.radiator_detskaia": "st_det",
    "climate.radiator_gostinaia": "st_gos",
    "climate.radiator_spalnia": "st_spa",
}

# key, суффикс помощника, icon, запасное время.
# Сон 21:00 — на два часа раньше прежнего отхода в 23:00.
_SLOTS: tuple[tuple[str, str, str, dt_time], ...] = (
    ("sched_comfort", "comfort", "mdi:weather-sunny", dt_time(7, 0)),
    ("sched_sleep", "sleep", "mdi:sleep", dt_time(21, 0)),
)


def _parse_helper_time(raw: str | None, fallback: dt_time) -> dt_time:
    if not raw or raw in ("unknown", "unavailable", "none"):
        return fallback
    parts = raw.strip().split(":")
    if len(parts) < 2:
        return fallback
    try:
        second = int(parts[2]) if len(parts) > 2 else 0
        return dt_time(int(parts[0]), int(parts[1]), second)
    except ValueError:
        return fallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    climate = entry.data.get(CONF_CLIMATE)
    prefix = _ROOM_PREFIX.get(climate or "")
    if prefix is None:
        _LOGGER.warning(
            "Нет своего расписания для %s — слоты времени не созданы", climate
        )
        return
    async_add_entities(
        ScheduleSlotTime(
            hass,
            entry,
            key,
            f"input_datetime.{prefix}_{suffix}",
            icon,
            fallback,
        )
        for key, suffix, icon, fallback in _SLOTS
    )


class ScheduleSlotTime(TimeEntity):
    """Слот расписания. Без категории — попадает в «Управление» устройства."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        key: str,
        helper: str,
        icon: str,
        fallback: dt_time,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._helper = helper
        self._fallback = fallback
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        climate = entry.data.get(CONF_CLIMATE)
        friendly = None
        if climate:
            state = hass.states.get(climate)
            if state is not None:
                friendly = state.attributes.get("friendly_name")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=thermostat_device_label(climate, friendly),
            manufacturer="Custom",
            model="Smart Thermostat",
        )

    @property
    def native_value(self) -> dt_time:
        state = self.hass.states.get(self._helper)
        raw = state.state if state is not None else None
        return _parse_helper_time(raw, self._fallback)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._helper], self._on_helper
            )
        )

    @callback
    def _on_helper(self, _event) -> None:
        self.async_write_ha_state()

    async def async_set_value(self, value: dt_time) -> None:
        if self.hass.states.get(self._helper) is None:
            _LOGGER.warning(
                "Нет %s — время расписания некуда записать", self._helper
            )
            return
        await self.hass.services.async_call(
            "input_datetime",
            "set_datetime",
            {
                "entity_id": self._helper,
                "time": value.strftime("%H:%M:%S"),
            },
            blocking=True,
        )
        self.async_write_ha_state()
