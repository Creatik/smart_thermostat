from __future__ import annotations

import logging
from typing import Any  # Добавлен импорт Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    BooleanSelector,
)

from .const import (
    DOMAIN,
    CONF_CLIMATE,
    CONF_ROOM_SENSORS,
    CONF_ROOM_TARGET,
    CONF_WINDOW_SENSORS,
    CONF_INTERVAL_SEC,
    CONF_DEADBAND,
    CONF_STEP_MAX,
    CONF_STEP_MIN,
    CONF_LEARN_RATE_FAST,
    CONF_LEARN_RATE_SLOW,
    CONF_TRV_MIN,
    CONF_TRV_MAX,
    CONF_COOLDOWN_SEC,
    CONF_BOOST_DURATION_SEC,
    CONF_ENABLE_LEARNING,
    CONF_STUCK_ENABLE,
    CONF_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP,
    CONF_STUCK_STEP,
    CONF_MIN_OFFSET_CHANGE,
    CONF_NO_LEARN_SUMMER,
    CONF_WINDOW_OPEN_NO_LEARN_MIN,
    CONF_HEATING_ALPHA,
    CONF_OVERSHOOT_THRESHOLD,
    CONF_PREDICT_MINUTES,
    CONF_STABLE_LEARN_SECONDS,
    CONF_STABLE_LEARN_ALPHA,
    CONF_OFFSET_DECAY_RATE,
    CONF_OFFSET_DECAY_THRESHOLD,
    CONF_OFFSET_LEARN_THRESHOLD,
    CONF_MAX_STUCK_BIAS,
    CONF_TTT_ALPHA,
    CONF_TTT_SOFT_MIN,
    CONF_OUTDOOR_SENSOR,
    CONF_WEATHER_ENTITY,
    DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_entity_list(value: Any) -> list[str]:
    """Нормализация значений селектора в список entity_id."""
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


class SmartThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для Smart Thermostat."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Шаг настройки основных параметров."""
        errors = {}

        if user_input is not None:
            room_sensors = _normalize_entity_list(user_input[CONF_ROOM_SENSORS])
            if not room_sensors:
                errors["base"] = "no_room_sensor"
            else:
                user_input[CONF_ROOM_SENSORS] = room_sensors

            # Запрет дубликатов по термостату
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_CLIMATE) == user_input[CONF_CLIMATE]:
                    errors["base"] = "already_configured"
                    break

            if not errors:
                climate_name = user_input[CONF_CLIMATE].split(".")[-1]
                sensors_name = ", ".join([s.split(".")[-1] for s in room_sensors[:3]])
                if len(room_sensors) > 3:
                    sensors_name += "…"
                title = f"Smart Thermostat: {climate_name} ↔ {sensors_name}"

                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_CLIMATE): EntitySelector(
                EntitySelectorConfig(domain="climate", multiple=False)
            ),
            vol.Required(CONF_ROOM_SENSORS): EntitySelector(
                EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(CONF_WINDOW_SENSORS): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(CONF_ROOM_TARGET, default=22.0): NumberSelector(
                NumberSelectorConfig(
                    min=5.0, max=30.0, step=0.5,
                    mode=NumberSelectorMode.BOX, unit_of_measurement="°C"
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Smart Thermostat",
                "desc": "Выберите термостат, один или несколько датчиков температуры помещения и целевую температуру."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return SmartThermostatOptionsFlow(config_entry)


class SmartThermostatOptionsFlow(config_entries.OptionsFlow):
    """Поток опций для тонкой настройки."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            changed_keys = [
                k for k, v in user_input.items()
                if self._config_entry.options.get(k) != v
            ]
            if changed_keys:
                _LOGGER.info(
                    "Изменены опции для %s: %s",
                    self._config_entry.entry_id, changed_keys
                )
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options

        def get_option(key, default=None):
            return opts.get(key, DEFAULTS.get(key, default))

        schema = vol.Schema({
            vol.Optional(
                CONF_WINDOW_SENSORS,
                default=get_option(CONF_WINDOW_SENSORS, [])
            ): EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True)),

            vol.Optional(CONF_INTERVAL_SEC, default=get_option(CONF_INTERVAL_SEC)): NumberSelector(
                NumberSelectorConfig(min=60, max=1800, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),

            vol.Optional(CONF_DEADBAND, default=get_option(CONF_DEADBAND)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=2.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_STEP_MAX, default=get_option(CONF_STEP_MAX)): NumberSelector(
                NumberSelectorConfig(min=0.1, max=5.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_STEP_MIN, default=get_option(CONF_STEP_MIN)): NumberSelector(
                NumberSelectorConfig(min=0.05, max=2.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_LEARN_RATE_FAST, default=get_option(CONF_LEARN_RATE_FAST)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.01, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_LEARN_RATE_SLOW, default=get_option(CONF_LEARN_RATE_SLOW)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.01, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_MIN_OFFSET_CHANGE, default=get_option(CONF_MIN_OFFSET_CHANGE)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_ENABLE_LEARNING, default=get_option(CONF_ENABLE_LEARNING)): BooleanSelector(),

            vol.Optional(CONF_NO_LEARN_SUMMER, default=get_option(CONF_NO_LEARN_SUMMER)): BooleanSelector(),

            vol.Optional(CONF_WINDOW_OPEN_NO_LEARN_MIN, default=get_option(CONF_WINDOW_OPEN_NO_LEARN_MIN)): NumberSelector(
                NumberSelectorConfig(min=0, max=1440, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="min")
            ),

            vol.Optional(CONF_TRV_MIN, default=get_option(CONF_TRV_MIN)): NumberSelector(
                NumberSelectorConfig(min=5.0, max=25.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_TRV_MAX, default=get_option(CONF_TRV_MAX)): NumberSelector(
                NumberSelectorConfig(min=15.0, max=35.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_COOLDOWN_SEC, default=get_option(CONF_COOLDOWN_SEC)): NumberSelector(
                NumberSelectorConfig(min=0, max=3600, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),

            vol.Optional(CONF_BOOST_DURATION_SEC, default=get_option(CONF_BOOST_DURATION_SEC)): NumberSelector(
                NumberSelectorConfig(min=30, max=7200, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),

            vol.Optional(CONF_STUCK_ENABLE, default=get_option(CONF_STUCK_ENABLE)): BooleanSelector(),

            vol.Optional(CONF_STUCK_SECONDS, default=get_option(CONF_STUCK_SECONDS)): NumberSelector(
                NumberSelectorConfig(min=300, max=86400, step=60, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),

            vol.Optional(CONF_STUCK_MIN_DROP, default=get_option(CONF_STUCK_MIN_DROP)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=3.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_STUCK_STEP, default=get_option(CONF_STUCK_STEP)): NumberSelector(
                NumberSelectorConfig(min=0.05, max=5.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_HEATING_ALPHA, default=get_option(CONF_HEATING_ALPHA)): NumberSelector(
                NumberSelectorConfig(min=0.01, max=0.5, step=0.01, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_OVERSHOOT_THRESHOLD, default=get_option(CONF_OVERSHOOT_THRESHOLD)): NumberSelector(
                NumberSelectorConfig(min=0.1, max=2.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_PREDICT_MINUTES, default=get_option(CONF_PREDICT_MINUTES)): NumberSelector(
                NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min")
            ),

            vol.Optional(CONF_STABLE_LEARN_SECONDS, default=get_option(CONF_STABLE_LEARN_SECONDS)): NumberSelector(
                NumberSelectorConfig(min=300, max=3600, step=60, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),

            vol.Optional(CONF_STABLE_LEARN_ALPHA, default=get_option(CONF_STABLE_LEARN_ALPHA)): NumberSelector(
                NumberSelectorConfig(min=0.05, max=0.5, step=0.01, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_OFFSET_DECAY_RATE, default=get_option(CONF_OFFSET_DECAY_RATE)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=0.1, step=0.001, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_OFFSET_DECAY_THRESHOLD, default=get_option(CONF_OFFSET_DECAY_THRESHOLD)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_OFFSET_LEARN_THRESHOLD, default=get_option(CONF_OFFSET_LEARN_THRESHOLD)): NumberSelector(
                NumberSelectorConfig(min=0.1, max=2.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_MAX_STUCK_BIAS, default=get_option(CONF_MAX_STUCK_BIAS)): NumberSelector(
                NumberSelectorConfig(min=1.0, max=10.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),

            vol.Optional(CONF_TTT_ALPHA, default=get_option(CONF_TTT_ALPHA)): NumberSelector(
                NumberSelectorConfig(min=0.05, max=0.5, step=0.01, mode=NumberSelectorMode.BOX)
            ),

            vol.Optional(CONF_TTT_SOFT_MIN, default=get_option(CONF_TTT_SOFT_MIN)): NumberSelector(
                NumberSelectorConfig(min=2, max=30, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min")
            ),

            vol.Optional(
                CONF_OUTDOOR_SENSOR,
                default=get_option(CONF_OUTDOOR_SENSOR)
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),

            vol.Optional(
                CONF_WEATHER_ENTITY,
                default=get_option(CONF_WEATHER_ENTITY)
            ): EntitySelector(
                EntitySelectorConfig(domain="weather")
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "title": "Параметры управления",
                "desc": "Тонкая настройка поведения контроллера. Изменения применяются сразу."
            },
        )