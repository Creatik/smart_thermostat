from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence
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
from .const import DOMAIN, SIGNAL_UPDATE, CONF_ROOM_TARGET

import json

@dataclass(frozen=True)
class _Def:
    key: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    options: Sequence[str] | None = None
    suggested_display_precision: int | None = None

LAST_ACTION_OPTIONS = (
    "init", "heating", "idle", "window_open", "boost", "error", "waiting",
    "no_temp", "skipped_unavailable_entities", "set_temperature", "cooling_needed",
    "overheated", "long_idle_min_temp", "stable_learn", "hold", "target_changed",
    "deadband_init", "min_interval_protection", "cooldown", "no_need_change",
    "set_failed", "reset_offset", "stable_learn", "set_failed", "control_paused",
    "deadband_rebase", "stuck_overtemp_down", "skipped_no_change",
)

SENSORS = (
    _Def(key="error", unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=3),
    _Def(key="offset", unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=3),
    _Def(key="target_trv", unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2),
    _Def(key="last_set", unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2),
    _Def(key="last_action"),
    _Def(key="last_action_text", device_class=SensorDeviceClass.ENUM, options=LAST_ACTION_OPTIONS),
    _Def(key="change_count", state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=0),
    _Def(key="window_state", device_class=SensorDeviceClass.ENUM, options=["open", "closed"]),
    _Def(key="boost_remaining", unit=UnitOfTime.SECONDS, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT),
    _Def(key="boost_active", device_class=SensorDeviceClass.ENUM, options=["on", "off"]),
    _Def(key="control_paused", device_class=SensorDeviceClass.ENUM, options=["on", "off"]),
    # New: history_graph sensor (JSON list for graphing in Lovelace)
    _Def(key="history_graph"),
    _Def(
        key="heating_rate",
        unit="°C/min",
        device_class=SensorDeviceClass.TEMPERATURE,  # или None
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
    ),
    _Def(
        key="predicted_time",
        unit=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.entry_id not in hass.data[DOMAIN]:
        return
    controller = hass.data[DOMAIN][entry.entry_id]
    entities = [SmartOffsetDebugSensor(hass, entry, controller, d) for d in SENSORS]
    async_add_entities(entities)

class SmartOffsetDebugSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller,
        definition: _Def,
    ):
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
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {
            "thermostat": self.entry.data.get("climate"),
            "room_sensor": self.entry.data.get("room_sensor"),
            "room_target": self.controller.opt(CONF_ROOM_TARGET),
        }
        if self.definition.key == "history_graph":
            attrs["history_json"] = json.dumps(self.controller._history_data)
            attrs["history_data"] = self.controller._history_data
        if self.definition.key in ["last_action", "last_action_text"]:
            attrs.update(
                {
                    "last_error": self.controller.last_error,
                    "window_is_open": getattr(self.controller, "window_is_open", False),
                    "boost_active": getattr(self.controller, "boost_active", False),
                    "change_count": getattr(self.controller, "change_count", 0),
                }
            )
        if self.definition.key == "history_graph":
            attrs["data_points"] = self.controller._history_data  # for custom graphing
        return attrs

    @property
    def native_value(self):
        k = self.definition.key
        try:
            if k == "error":
                err = self.controller.last_error
                return err if err is not None else 0.0
            if k == "offset":
                return round(float(self.controller.storage.get_offset(self.entry.entry_id) or 0), 3)
            if k == "target_trv":
                val = self.controller.last_target_trv
                return round(float(val), 2) if val is not None else None
            if k == "history_graph":
                count = len(self.controller._history_data)
                if count == 0:
                    return "No data yet"
                return f"{count} points (last update)"
            if k == "last_set":
                val = self.controller.last_set
                return round(float(val), 2) if val is not None else None
            if k == "last_action":
                return str(getattr(self.controller, "last_action", "init"))
            if k == "last_action_text":
                action = str(getattr(self.controller, "last_action", "init"))
                if action not in self._attr_options:
                    mapping = {
                        "skipped_unavailable_entities": "waiting",
                        "set_temperature": "set",
                        "set_failed": "error",
                        "no_need_change": "hold",
                        "min_interval_protection": "hold",
                        "cooldown": "hold",
                        "overheated": "idle",
                        "long_idle_min_temp": "idle",
                    }
                    return mapping.get(action, "unknown")
                return action
            if k == "change_count":
                return int(getattr(self.controller, "change_count", 0))
            if k == "window_state":
                return "open" if getattr(self.controller, "window_is_open", False) else "closed"
            if k == "boost_remaining":
                if not getattr(self.controller, "boost_active", False):
                    return 0
                until = getattr(self.controller, "boost_until", 0)
                return max(0, int(until - self.hass.loop.time()))
            if k == "boost_active":
                active = getattr(self.controller, "boost_active", False)
                until = getattr(self.controller, "boost_until", 0)
                return "on" if active and self.hass.loop.time() < until else "off"
            if k == "control_paused":
                wo = getattr(self.controller, "window_is_open", False)
                ba = getattr(self.controller, "boost_active", False)
                until = getattr(self.controller, "boost_until", 0)
                paused = wo or (ba and self.hass.loop.time() < until)
                return "on" if paused else "off"
            if k == "history_graph":
                # Return JSON string for graphing (e.g., in ApexCharts card)
                import json
                return json.dumps(self.controller._history_data)
            if k == "heating_rate":
                rate = getattr(self.controller, "_heating_rate", 0.1)
                return round(float(rate), 3) if rate is not None else None

            # если добавили predicted_time
            if k == "predicted_time":
                if hasattr(self.controller, "_heating_rate") and self.controller._heating_rate > 0.001:
                    e = self.controller.last_error
                    if e is not None and e > 0:
                        return round(e / self.controller._heating_rate, 1)  # минуты
                return None

            # если добавили learn_rate_current (текущий коэффициент обучения)
            if k == "learn_rate_current":
                # можно возвращать текущий используемый learn_rate
                # но проще показать self._learn_rate_slow, если вы его ввели
                return round(getattr(self.controller, "_learn_rate_slow", 0.1), 3)
        except Exception as e:
            LOGGER.error("Error in sensor %s: %s", k, str(e))

        return None

    async def async_added_to_hass(self) -> None:
        @callback
        def _update():
            self.async_write_ha_state()
        self._unsub = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}",
            _update,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None