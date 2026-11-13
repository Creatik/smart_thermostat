from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, SIGNAL_UPDATE, CONF_CLIMATE
from .helpers import thermostat_device_label

_LOGGER = logging.getLogger(__name__)

# Тот же ключ, что у часов в time.py. Незнакомая головка не получает тумблер.
_ROOM_PREFIX = {
    "climate.radiator_detskaia": "st_det",
    "climate.radiator_gostinaia": "st_gos",
    "climate.radiator_spalnia": "st_spa",
}


def _device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    climate = entry.data.get(CONF_CLIMATE)
    friendly = None
    if climate:
        state = hass.states.get(climate)
        if state is not None:
            friendly = state.attributes.get("friendly_name")
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=thermostat_device_label(climate, friendly),
        manufacturer="Custom",
        model="Smart Thermostat",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [SmartOffsetBoostSwitch(hass, entry, controller)]
    prefix = _ROOM_PREFIX.get(entry.data.get(CONF_CLIMATE) or "")
    if prefix:
        entities.append(
            ScheduleEnableSwitch(hass, entry, f"input_boolean.{prefix}_schedule")
        )
    async_add_entities(entities)

class SmartOffsetBoostSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Optional[Callable[[], None]] = None

        self._attr_unique_id = f"{entry.entry_id}_boost"
        self._attr_translation_key = "boost"
        self._attr_icon = "mdi:fire"

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.hass, self.entry)

    @property
    def is_on(self) -> bool:
        return bool(self.controller.boost_active and (self.hass.loop.time() < self.controller.boost_until))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.start_boost()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller._cancel_boost()
        await self.controller.trigger_once()
        self.controller._notify()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        @callback
        def _update():
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(
            self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}", _update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None


class ScheduleEnableSwitch(SwitchEntity):
    """Ручное включение часов этой комнаты. Пока выключен, цель не трогаем."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "sched_enabled"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, helper: str) -> None:
        self.hass = hass
        self.entry = entry
        self._helper = helper
        self._attr_unique_id = f"{entry.entry_id}_sched_enabled"

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.hass, self.entry)

    @property
    def is_on(self) -> bool:
        return self.hass.states.is_state(self._helper, "on")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._helper], self._on_helper)
        )

    @callback
    def _on_helper(self, _event) -> None:
        self.async_write_ha_state()

    async def _set(self, on: bool) -> None:
        if self.hass.states.get(self._helper) is None:
            _LOGGER.warning("Нет %s — расписание некуда включить", self._helper)
            return
        await self.hass.services.async_call(
            "input_boolean",
            "turn_on" if on else "turn_off",
            {"entity_id": self._helper},
            blocking=True,
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
