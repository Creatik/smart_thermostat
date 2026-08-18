from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence
import json
import logging


from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from .const import (
    DOMAIN,
    SIGNAL_UPDATE,
    CONF_ROOM_TARGET,
    CONF_CLIMATE,
    CONF_ROOM_SENSORS,
)




_LOGGER = logging.getLogger(__name__)




@dataclass(frozen=True)
class SensorDefinition:
    """Определение сенсора."""
    key: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    options: Sequence[str] | None = None
    suggested_display_precision: int | None = None




# Маппинг действий для last_action_text
ACTION_MAPPING = {
    "skipped_unavailable_entities": "waiting",
    "set_temperature": "set",
    "set_failed": "error",
    "no_need_change": "hold",
    "min_interval_protection": "hold",
    "cooldown": "hold",
    "overheated": "idle",
    "long_idle_min_temp": "idle",
    "stuck_overtemp_down": "stuck",
    "deadband_rebase": "rebase",
    "deadband_init": "init",
    "stable_learn": "learn",
    "reset_offset": "reset",
    "window_open": "window",
    "boost": "boost",
    "hold": "hold",
    "heating": "heating",
    "idle": "idle",
    "error": "error",
    "waiting": "waiting",
    "init": "init",
    "no_room_sensors": "no_sensors",
    "no_valid_room_temp": "no_temp",
    "climate_unavailable": "climate_off",
}




# Доступные действия для ENUM сенсора
# ИСПРАВЛЕНО: добавлено значение "unknown" в список опций
LAST_ACTION_OPTIONS = sorted(set(ACTION_MAPPING.values()) | {"unknown", "no_sensors", "no_temp", "climate_off"})




SENSORS = (
    SensorDefinition(
        key="error",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3
    ),
    SensorDefinition(
        key="offset",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3
    ),
    SensorDefinition(
        key="target_trv",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2
    ),
    SensorDefinition(
        key="last_set",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2
    ),
    SensorDefinition(key="last_action"),
    SensorDefinition(
        key="last_action_text",
        device_class=SensorDeviceClass.ENUM,
        options=LAST_ACTION_OPTIONS
    ),
    SensorDefinition(
        key="change_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0
    ),
    SensorDefinition(
        key="window_state",
        device_class=SensorDeviceClass.ENUM,
        options=["open", "closed"]
    ),
    SensorDefinition(
        key="boost_remaining",
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT
    ),
    SensorDefinition(
        key="boost_active",
        device_class=SensorDeviceClass.ENUM,
        options=["on", "off"]
    ),
    SensorDefinition(
        key="control_paused",
        device_class=SensorDeviceClass.ENUM,
        options=["on", "off"]
    ),
    SensorDefinition(
        key="heating_rate",
        unit="°C/min",  # строка
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3
    ),
    SensorDefinition(
        key="predicted_time",
        unit="min",  # строка — решает проблему
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1
    ),
    SensorDefinition(
        key="device_temperature",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1
    ),
)




async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка сенсоров для конфигурационной записи."""
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    
    controller = hass.data[DOMAIN][entry.entry_id]
    entities = [SmartOffsetDebugSensor(hass, entry, controller, d) for d in SENSORS]
    async_add_entities(entities)




class SmartOffsetDebugSensor(SensorEntity):
    """Сенсор для отладки Smart Thermostat."""
    
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True # Активировать сенсоры для отладки
    _attr_should_poll = False


    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller,
        definition: SensorDefinition,
    ):
        """Инициализация сенсора."""
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self.definition = definition
        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
        self._attr_translation_key = definition.key
        self._attr_native_unit_of_measurement = definition.unit
        
        if definition.device_class:
            self._attr_device_class = definition.device_class
        if definition.state_class:
            self._attr_state_class = definition.state_class
        if definition.suggested_display_precision is not None:
            self._attr_suggested_display_precision = definition.suggested_display_precision
        if definition.options:
            self._attr_options = list(definition.options)
        
        self._unsub: Optional[Callable[[], None]] = None


    @property
    def device_info(self) -> DeviceInfo:
        """Информация об устройстве."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Thermostat",
            manufacturer="Custom",
            model="Smart Thermostat",
        )


    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Дополнительные атрибуты сенсора."""
        attrs = {
            "thermostat": self.entry.data.get(CONF_CLIMATE),
            "room_sensor": self.entry.data.get(CONF_ROOM_SENSORS),
            "room_target": self.controller.opt(CONF_ROOM_TARGET),
        }
        
        
        if self.definition.key in ["last_action", "last_action_text"]:
            attrs.update({
                "last_error": self.controller.last_error,
                "window_is_open": getattr(self.controller, "window_is_open", False),
                "boost_active": getattr(self.controller, "boost_active", False),
                "change_count": getattr(self.controller, "change_count", 0),
                "last_set": self.controller.last_set,
                "last_target_trv": self.controller.last_target_trv,
            })
        
        return attrs


    @property
    def native_value(self):
        """Текущее значение сенсора."""
        k = self.definition.key
        
        try:
            # Обработка error сенсора
            if k == "error":
                err = self.controller.last_error
                return round(float(err or 0.0), 3)
            
            # Обработка offset сенсора
            elif k == "offset":
                offset = self.controller.storage.get_offset(self.entry.entry_id)
                return round(float(offset or 0.0), 3)
            
            # Обработка target_trv сенсора
            elif k == "target_trv":
                val = self.controller.last_target_trv
                return round(float(val), 2) if val is not None else None
            
            elif k == "device_temperature":
                climate_entity = self.entry.data.get(CONF_CLIMATE)
                if not climate_entity:
                    return None
                
                state = self.hass.states.get(climate_entity)
                if not state or state.state in ("unavailable", "unknown"):
                    return None
                
                # Пробуем разные атрибуты (разные интеграции называют по-разному)
                for attr in ["current_temperature", "local_temperature", "temperature"]:
                    temp = state.attributes.get(attr)
                    if temp is not None:
                        try:
                            return round(float(temp), 1)
                        except (ValueError, TypeError):
                            pass
                
                return None
            # Обработка last_set сенсора
            elif k == "last_set":
                val = self.controller.last_set
                return round(float(val), 2) if val is not None else None
            
            # Обработка last_action сенсора
            elif k == "last_action":
                action = getattr(self.controller, "last_action", "init")
                return str(action)
            
            # Обработка last_action_text сенсора
            elif k == "last_action_text":
                action = str(getattr(self.controller, "last_action", "init"))
                return ACTION_MAPPING.get(action, "unknown")
            
            # Обработка change_count сенсора
            elif k == "change_count":
                return int(getattr(self.controller, "change_count", 0))
            
            # Обработка window_state сенсора
            elif k == "window_state":
                is_open = getattr(self.controller, "window_is_open", False)
                return "open" if is_open else "closed"
            
            # Обработка boost_remaining сенсора
            elif k == "boost_remaining":
                if not getattr(self.controller, "boost_active", False):
                    return 0
                until = getattr(self.controller, "boost_until", 0)
                remaining = max(0, int(until - self.hass.loop.time()))
                return remaining
            
            # Обработка boost_active сенсора
            elif k == "boost_active":
                active = getattr(self.controller, "boost_active", False)
                until = getattr(self.controller, "boost_until", 0)
                is_active = active and self.hass.loop.time() < until
                return "on" if is_active else "off"
            
            # Обработка control_paused сенсора
            elif k == "control_paused":
                wo = getattr(self.controller, "window_is_open", False)
                ba = getattr(self.controller, "boost_active", False)
                until = getattr(self.controller, "boost_until", 0)
                paused = wo or (ba and self.hass.loop.time() < until)
                return "on" if paused else "off"
            
            # Обработка heating_rate сенсора
            elif k == "heating_rate":
                rate = getattr(self.controller, "_heating_rate", 0.1)
                return round(float(rate), 3) if rate is not None else None
            
            # Обработка predicted_time сенсора
            elif k == "predicted_time":
                heating_rate = getattr(self.controller, "_heating_rate", 0.1)
                error = self.controller.last_error
                
                if heating_rate > 0.001 and error is not None and error > 0:
                    # Рассчитываем время в минутах
                    time_minutes = error / heating_rate
                    return round(time_minutes, 1)
                return None
            
            # Обработка learn_rate_current сенсора (если добавлен)
            elif k == "learn_rate_current":
                learn_rate = getattr(self.controller, "_learn_rate_slow", 0.1)
                return round(float(learn_rate), 3)
            
        except Exception as e:
            _LOGGER.error("Error in sensor %s: %s", k, str(e), exc_info=True)
        
        return None


    async def async_added_to_hass(self) -> None:
        """Вызывается при добавлении сенсора в Home Assistant."""
        @callback
        def _update():
            """Обновить состояние сенсора."""
            self.async_write_ha_state()
        
        # Подписываемся на обновления от контроллера
        self._unsub = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}",
            _update,
        )
        
        # Первоначальное обновление
        self.async_write_ha_state()


    async def async_will_remove_from_hass(self) -> None:
        """Вызывается при удалении сенсора из Home Assistant."""
        if self._unsub:
            self._unsub()
            self._unsub = None