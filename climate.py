from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode, 
    ClimateEntityFeature,
    HVACAction,
    SERVICE_SET_HVAC_MODE,
)

from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature, EVENT_STATE_CHANGED

from .const import DOMAIN, SIGNAL_UPDATE, CONF_ROOM_TARGET, CONF_ROOM_SENSORS, DEFAULTS, CONF_CLIMATE


def _to_float(value: Any) -> Optional[float]:
    """Безопасное преобразование в float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_entity_list(value: Any) -> list[str]:
    """Нормализация списка entity_id."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if v is None:
                continue
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and "entity_id" in v:
                out.append(v["entity_id"])
        return [x for x in out if x]
    return []


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
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"
    _attr_translation_key = "virtual_thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        """Initialize the virtual thermostat."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub_dispatcher: Optional[Callable[[], None]] = None
        self._unsub_room_sensors: Optional[Callable[[], None]] = None
        
        self._attr_unique_id = f"{entry.entry_id}_virtual_thermostat"
        self._attr_name = "Smart Thermostat"
        
        # Инициализируем hvac_action
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

    def _get_room_temperature(self) -> Optional[float]:
        """Получить усреднённую температуру по всем датчикам помещения."""
        room_entities = _normalize_entity_list(self.entry.data.get(CONF_ROOM_SENSORS, []))
        if not room_entities:
            return None

        temps = []
        for entity in room_entities:
            state = self.hass.states.get(entity)
            if state is None:
                continue
            t = _to_float(state.state)
            if t is not None:
                temps.append(t)

        if not temps:
            return None

        return sum(temps) / len(temps)  # среднее арифметическое

    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature (усреднённая по всем датчикам)."""
        return self._get_room_temperature()

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
    def hvac_mode(self) -> HVACMode:
        """Return current hvac mode."""
        # Берем из опций, по умолчанию HEAT
        mode_raw = self.entry.options.get("hvac_mode", HVACMode.HEAT.value)
        if isinstance(mode_raw, HVACMode):
            return mode_raw
        try:
            return HVACMode(str(mode_raw))
        except ValueError:
            return HVACMode.HEAT

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            return

        # сохранить режим
        new_options = dict(self.entry.options)
        new_options["hvac_mode"] = hvac_mode.value
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

        # реальный TRV
        real_climate = self.entry.data.get(CONF_CLIMATE)
        if not real_climate:
            return

        await self.hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": real_climate, "hvac_mode": hvac_mode.value},
            blocking=True,
        )

        await self.controller.trigger_once(force=True)

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action based on temperature difference."""

        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        
        current_temp = self.current_temperature
        target_temp = self.target_temperature
        
        if current_temp is None or target_temp is None:
            return HVACAction.IDLE
        
        deadband = float(self.controller.opt("deadband") or DEFAULTS.get("deadband", 0.2))
        error = target_temp - current_temp
        
        if error > deadband:
            return HVACAction.HEATING
        elif error < -deadband:
            return HVACAction.IDLE
        else:
            # В deadband — используем последнее действие контроллера
            last_action = getattr(self.controller, "last_action", "")
            if "heating" in last_action or "set_temperature" in last_action:
                return HVACAction.HEATING
            return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        room_entities = _normalize_entity_list(self.entry.data.get(CONF_ROOM_SENSORS, []))
        return {
            "thermostat": self.entry.data.get(CONF_CLIMATE),
            "room_sensors": room_entities,
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
        def _update_state():
            """Update climate entity state."""
            self.async_write_ha_state()
        
        # Подписка на обновления от контроллера
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, 
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}", 
            _update_state
        )
        
        # Подписка на изменения всех датчиков температуры
        room_entities = _normalize_entity_list(self.entry.data.get(CONF_ROOM_SENSORS, []))
        
        if room_entities:
            @callback
            def _room_sensor_changed(event: Event):
                """Handle changes in any room sensor."""
                changed_entity = event.data.get("entity_id")
                if changed_entity in room_entities:
                    _update_state()
            
            self._unsub_room_sensors = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                _room_sensor_changed
            )

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        
        if self._unsub_room_sensors:
            self._unsub_room_sensors()
            self._unsub_room_sensors = None