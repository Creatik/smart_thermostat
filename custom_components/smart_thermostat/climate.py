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
)

from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature, EVENT_STATE_CHANGED

from .const import (
    DOMAIN,
    SIGNAL_UPDATE,
    CONF_ROOM_TARGET,
    CONF_ROOM_SENSORS,
    DEFAULTS,
    CONF_CLIMATE,
    PRESET_NONE,
    PRESET_MODES,
)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_entity_list(value: Any) -> list[str]:
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
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartThermostatVirtual(hass, entry, controller)])


class SmartThermostatVirtual(ClimateEntity):
    """Virtual thermostat that shows room temperature and target."""
    
    _attr_has_entity_name = True
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TURN_ON |
        ClimateEntityFeature.TURN_OFF |
        ClimateEntityFeature.PRESET_MODE
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"
    _attr_translation_key = "virtual_thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub_dispatcher: Optional[Callable[[], None]] = None
        self._unsub_room_sensors: Optional[Callable[[], None]] = None
        
        self._attr_unique_id = f"{entry.entry_id}_virtual_thermostat"
        self._attr_name = "Умный термостат"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Thermostat",
            manufacturer="Custom",
            model="Smart Thermostat",
        )

    def _get_room_temperature(self) -> Optional[float]:
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

        return sum(temps) / len(temps)

    @property
    def current_temperature(self) -> float | None:
        return self._get_room_temperature()

    @property
    def target_temperature(self) -> float | None:
        try:
            return float(self.controller.active_target())
        except (ValueError, TypeError):
            return float(DEFAULTS[CONF_ROOM_TARGET])

    @property
    def preset_modes(self) -> list[str]:
        """Доступные пресеты (none, comfort, eco, away, sleep)."""
        return list(PRESET_MODES)

    @property
    def preset_mode(self) -> str:
        """Активный пресет."""
        preset = self.controller.active_preset()
        return preset if preset else PRESET_NONE

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Переключить пресет."""
        if preset_mode not in PRESET_MODES:
            return
        await self.controller.set_preset(preset_mode)
        self.async_write_ha_state()

    @property
    def min_temp(self) -> float:
        try:
            return float(self.controller.opt("trv_min") or 5.0)
        except (ValueError, TypeError):
            return 5.0

    @property
    def max_temp(self) -> float:
        try:
            return float(self.controller.opt("trv_max") or 35.0)
        except (ValueError, TypeError):
            return 35.0

    @property
    def hvac_mode(self) -> HVACMode:
        mode_raw = self.entry.options.get("hvac_mode", HVACMode.HEAT.value)
        try:
            return HVACMode(mode_raw)
        except ValueError:
            return HVACMode.HEAT

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            return

        # Сохраняем режим в опциях
        new_options = dict(self.entry.options)
        new_options["hvac_mode"] = hvac_mode.value
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

        # Передаём режим реальному TRV
        real_climate = self.entry.data.get(CONF_CLIMATE)
        if real_climate:
            if hvac_mode == HVACMode.OFF:
                service = "turn_off"
                try:
                    await self.hass.services.async_call("climate", service, {"entity_id": real_climate}, blocking=True)
                except Exception:
                    # Fallback: низкая уставка, если turn_off не поддерживается
                    trv_min = self.min_temp
                    await self.hass.services.async_call("climate", "set_temperature", {"entity_id": real_climate, ATTR_TEMPERATURE: trv_min}, blocking=True)
            else:
                service = "turn_on"
                await self.hass.services.async_call("climate", service, {"entity_id": real_climate}, blocking=True)

            # Перезапуск контроллера
            await self.controller.trigger_once(force=True)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction:
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
            last_action = getattr(self.controller, "last_action", "")
            if "heating" in last_action or "set_temperature" in last_action:
                return HVACAction.HEATING
            return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
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
        if ATTR_TEMPERATURE not in kwargs:
            return
        
        new_target = float(kwargs[ATTR_TEMPERATURE])

        # Ручная установка температуры сбрасывает активный пресет (переход в 'none')
        if self.controller.active_preset():
            await self.controller.set_preset(PRESET_NONE)

        new_options = dict(self.entry.options)
        new_options[CONF_ROOM_TARGET] = new_target
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

        await self.controller.trigger_once(force=True)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_state():
            self.async_write_ha_state()
        
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, 
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}", 
            _update_state
        )
        
        room_entities = _normalize_entity_list(self.entry.data.get(CONF_ROOM_SENSORS, []))
        if room_entities:
            @callback
            def _room_sensor_changed(event: Event):
                if event.data.get("entity_id") in room_entities:
                    _update_state()
            
            self._unsub_room_sensors = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED,
                _room_sensor_changed
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
        if self._unsub_room_sensors:
            self._unsub_room_sensors()