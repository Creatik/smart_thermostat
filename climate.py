from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode, 
    ClimateEntityFeature,
    HVACAction,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import DOMAIN, SIGNAL_UPDATE, CONF_ROOM_TARGET, DEFAULTS


async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up climate platform."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetVirtualThermostat(hass, entry, controller)])


class SmartOffsetVirtualThermostat(ClimateEntity):
    """Virtual thermostat that shows room temperature and target."""
    
    _attr_has_entity_name = True
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"
    _attr_translation_key = "virtual_thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        """Initialize the virtual thermostat."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Optional[Callable[[], None]] = None
        self._room_sensor_unsub: Optional[Callable[[], None]] = None
        
        self._attr_unique_id = f"{entry.entry_id}_virtual_thermostat"
        self._attr_name = "Smart Thermostat"
        
        # Initialize hvac_action
        self._attr_hvac_action = HVACAction.IDLE

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature."""
        room_sensor = self.entry.data.get("room_sensor_entity")
        if not room_sensor:
            return None
        
        room_state = self.hass.states.get(room_sensor)
        if not room_state:
            return None
        
        try:
            return float(room_state.state)
        except (ValueError, TypeError):
            return None

    @property
    def target_temperature(self) -> float | None:
        """Return target room temperature."""
        v = self.controller.opt(CONF_ROOM_TARGET)
        try:
            return float(v)
        except (ValueError, TypeError):
            return float(DEFAULTS[CONF_ROOM_TARGET])

    @property
    def min_temp(self) -> float:
        """Return minimum temperature."""
        try:
            return float(self.controller.opt("trv_min") or 5.0)
        except (ValueError, TypeError):
            return 5.0

    @property
    def max_temp(self) -> float:
        """Return maximum temperature."""
        try:
            return float(self.controller.opt("trv_max") or 35.0)
        except (ValueError, TypeError):
            return 35.0

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action based on temperature difference."""
        current_temp = self.current_temperature
        target_temp = self.target_temperature
        
        if current_temp is None or target_temp is None:
            return HVACAction.IDLE
        
        # Определяем состояние на основе разницы температур
        deadband = float(self.controller.opt("deadband") or 0.2)
        
        if current_temp < (target_temp - deadband):
            # Температура ниже целевой - нагреваем
            return HVACAction.HEATING
        elif current_temp > (target_temp + deadband):
            # Температура выше целевой - бездействуем
            return HVACAction.IDLE
        else:
            # В deadband - смотрим на последнее действие контроллера
            last_action = getattr(self.controller, "last_action", "")
            
            if last_action in ["heating", "set_temperature"]:
                return HVACAction.HEATING
            elif last_action in ["idle", "hold", "no_need_change"]:
                return HVACAction.IDLE
            else:
                # По умолчанию - бездействие
                return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "thermostat": self.entry.data.get("climate"),
            "room_sensor": self.entry.data.get("room_sensor_entity"),
            "offset": self.controller.storage.get_offset(self.entry.entry_id),
            "last_action": getattr(self.controller, "last_action", ""),
            "last_error": getattr(self.controller, "last_error", None),
            "window_open": getattr(self.controller, "window_is_open", False),
            "boost_active": getattr(self.controller, "boost_active", False),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            return
        
        new_target = float(kwargs[ATTR_TEMPERATURE])
        
        # Обновляем опции
        new_options = dict(self.entry.options)
        new_options[CONF_ROOM_TARGET] = new_target
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        
        # Запускаем контроллер
        await self.controller.trigger_once(force=True)
        
        # Обновляем UI
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        @callback
        def _update():
            """Update climate entity state."""
            self.async_write_ha_state()
        
        # Подписываемся на обновления от контроллера
        self._unsub = async_dispatcher_connect(
            self.hass, 
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}", 
            _update
        )
        
        # Также подписываемся на изменения датчика температуры
        room_sensor = self.entry.data.get("room_sensor_entity")
        if room_sensor:
            @callback
            def _room_sensor_changed(event):
                """Handle room sensor changes."""
                # Проверяем, что событие относится к нашему датчику
                if event.data.get("entity_id") == room_sensor:
                    self.async_write_ha_state()
            
            # Правильный способ подписаться на события state_changed
            self._room_sensor_unsub = self.hass.bus.async_listen(
                "state_changed",
                _room_sensor_changed
            )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        
        if self._room_sensor_unsub:
            self._room_sensor_unsub()
            self._room_sensor_unsub = None