"""Platform for button entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button platform."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return

    controller = hass.data[DOMAIN][entry.entry_id]
    
    buttons = [
        # SmartOffsetBoostButton(hass, entry, controller),
        SmartOffsetResetButton(hass, entry, controller),
    ]
    
    async_add_entities(buttons)


class SmartOffsetBaseButton(ButtonEntity):
    """Base button for Smart Offset Thermostat."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller,
    ) -> None:
        """Initialize the button."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )


# class SmartOffsetBoostButton(SmartOffsetBaseButton):
#     """Button to start boost mode."""
    
#     _attr_translation_key = "start_boost"

#     def __init__(
#         self,
#         hass: HomeAssistant,
#         entry: ConfigEntry,
#         controller,
#     ) -> None:
#         """Initialize the boost button."""
#         super().__init__(hass, entry, controller)
#         self._attr_unique_id = f"{entry.entry_id}_boost_button"

#     async def async_press(self) -> None:
#         """Handle the button press."""
#         _LOGGER.info("Boost button pressed for entry %s", self.entry.entry_id)
#         await self.controller.start_boost()


class SmartOffsetResetButton(SmartOffsetBaseButton):
    """Button to reset offset."""
    
    _attr_translation_key = "reset_offset"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller,
    ) -> None:
        """Initialize the reset button."""
        super().__init__(hass, entry, controller)
        self._attr_unique_id = f"{entry.entry_id}_reset_button"
        self._attr_translation_key = "reset_offset"
        self._attr_icon = "mdi:restart"

    async def async_press(self) -> None:
        """Handle the button press."""
        _LOGGER.info("Reset offset button pressed for entry %s", self.entry.entry_id)
        await self.controller.reset_offset()