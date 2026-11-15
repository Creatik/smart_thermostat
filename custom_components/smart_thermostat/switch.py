from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN, SIGNAL_UPDATE, CONF_CLIMATE
from .helpers import thermostat_device_label

_LOGGER = logging.getLogger(__name__)


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
    entities: list[SwitchEntity] = [
        SmartOffsetBoostSwitch(hass, entry, controller),
        ScheduleEnableSwitch(hass, entry, controller),
    ]
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
    """Включение часов этой комнаты. Пока выкл — цель не трогаем."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "sched_enabled"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._storage = controller.storage
        self._attr_unique_id = f"{entry.entry_id}_sched_enabled"
        self._unsub: Optional[Callable[[], None]] = None

    @property
    def device_info(self) -> DeviceInfo:
        return _device_info(self.hass, self.entry)

    @property
    def is_on(self) -> bool:
        return bool(self._storage.get_schedule(self.entry.entry_id).get("enabled"))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._storage.set_schedule(self.entry.entry_id, enabled=True)
        self.async_write_ha_state()
        await self.controller.trigger_once(force=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._storage.set_schedule(self.entry.entry_id, enabled=False)
        self.async_write_ha_state()
        await self.controller.trigger_once(force=True)
