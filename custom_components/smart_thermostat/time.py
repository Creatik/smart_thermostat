"""Два времени на странице устройства: комфорт днём и сон.

Хранятся в storage интеграции (на entry_id) — без привязки к entity_id
конкретного дома. Старые input_datetime.* подхватываются один раз при старте.
"""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE,
    DOMAIN,
    SCHEDULE_DEFAULT_COMFORT,
    SCHEDULE_DEFAULT_SLEEP,
)
from .helpers import parse_schedule_hhmm, thermostat_device_label

_LOGGER = logging.getLogger(__name__)

# key, суффикс storage, icon, запасное время.
_SLOTS: tuple[tuple[str, str, str, str], ...] = (
    ("sched_comfort", "comfort", "mdi:weather-sunny", SCHEDULE_DEFAULT_COMFORT),
    ("sched_sleep", "sleep", "mdi:sleep", SCHEDULE_DEFAULT_SLEEP),
)


def _hhmm_to_time(raw: str, fallback: str) -> dt_time:
    hhmm = parse_schedule_hhmm(raw, fallback)
    parts = hhmm.split(":")
    return dt_time(int(parts[0]), int(parts[1]))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ScheduleSlotTime(
            hass,
            entry,
            controller.storage,
            key,
            slot,
            icon,
            fallback,
        )
        for key, slot, icon, fallback in _SLOTS
    )


class ScheduleSlotTime(TimeEntity):
    """Слот расписания. Без категории — попадает в «Управление» устройства."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        storage,
        key: str,
        slot: str,
        icon: str,
        fallback: str,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._storage = storage
        self._slot = slot
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
        sched = self._storage.get_schedule(self.entry.entry_id)
        return _hhmm_to_time(str(sched.get(self._slot) or ""), self._fallback)

    async def async_set_value(self, value: dt_time) -> None:
        hhmm = value.strftime("%H:%M")
        if self._slot == "comfort":
            await self._storage.set_schedule(self.entry.entry_id, comfort=hhmm)
        else:
            await self._storage.set_schedule(self.entry.entry_id, sleep=hhmm)
        self.async_write_ha_state()
        # пнуть контроллер — слот мог сменить режим
        controller = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if controller is not None:
            await controller.trigger_once(force=True)
