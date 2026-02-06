from __future__ import annotations

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
from homeassistant.const import CONF_NAME  # если захочешь переименовать

from .const import (
    DOMAIN,
    CONF_CLIMATE,
    CONF_ROOM_SENSOR,
    CONF_ROOM_TARGET,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_SENSORS,
    CONF_INTERVAL_SEC,
    CONF_DEADBAND,
    CONF_STEP_MAX,
    CONF_STEP_MIN,
    CONF_LEARN_RATE,
    CONF_TRV_MIN,
    CONF_TRV_MAX,
    CONF_COOLDOWN_SEC,
    CONF_BOOST_DURATION_SEC,
    CONF_ENABLE_LEARNING,
    CONF_STUCK_ENABLE,
    CONF_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP,
    CONF_STUCK_STEP,
    DEFAULT_INTERVAL_SEC,
    DEFAULT_DEADBAND,
    DEFAULT_STEP_MAX,
    DEFAULT_STEP_MIN,
    DEFAULT_LEARN_RATE,
    DEFAULT_TRV_MIN,
    DEFAULT_TRV_MAX,
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_BOOST_DURATION_SEC,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_STUCK_ENABLE,
    DEFAULT_STUCK_SECONDS,
    DEFAULT_STUCK_MIN_DROP,
    DEFAULT_STUCK_STEP,
)

# Явные дефолты (если в const.py их нет — используй эти)
DEFAULTS = {
    CONF_INTERVAL_SEC: DEFAULT_INTERVAL_SEC or 300,
    CONF_DEADBAND: DEFAULT_DEADBAND or 0.3,
    CONF_STEP_MAX: DEFAULT_STEP_MAX or 1.0,
    CONF_STEP_MIN: DEFAULT_STEP_MIN or 0.5,
    CONF_LEARN_RATE: DEFAULT_LEARN_RATE or 0.05,
    CONF_TRV_MIN: DEFAULT_TRV_MIN or 5.0,
    CONF_TRV_MAX: DEFAULT_TRV_MAX or 30.0,
    CONF_COOLDOWN_SEC: DEFAULT_COOLDOWN_SEC or 120,
    CONF_BOOST_DURATION_SEC: DEFAULT_BOOST_DURATION_SEC or 600,
    CONF_ENABLE_LEARNING: DEFAULT_ENABLE_LEARNING or True,
    CONF_STUCK_ENABLE: DEFAULT_STUCK_ENABLE or True,
    CONF_STUCK_SECONDS: DEFAULT_STUCK_SECONDS or 1800,
    CONF_STUCK_MIN_DROP: DEFAULT_STUCK_MIN_DROP or 0.3,
    CONF_STUCK_STEP: DEFAULT_STUCK_STEP or 0.5,
}


class SmartOffsetThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Конфигурационный поток для Smart Offset Thermostat."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Первый шаг — выбор основных сущностей."""
        errors = {}

        if user_input is not None:
            # Проверяем, нет ли уже такой же интеграции (climate + room_sensor)
            existing_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in existing_entries:
                if (
                    entry.data.get(CONF_CLIMATE) == user_input[CONF_CLIMATE]
                    and entry.data.get(CONF_ROOM_SENSOR) == user_input[CONF_ROOM_SENSOR]
                ):
                    errors["base"] = "already_configured"
                    break

            if not errors:
                # Формируем красивое название
                title = f"Smart Offset: {user_input[CONF_CLIMATE].split('.')[-1]} ↔ {user_input[CONF_ROOM_SENSOR].split('.')[-1]}"
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_CLIMATE): EntitySelector(
                EntitySelectorConfig(domain="climate")
            ),
            vol.Required(CONF_ROOM_SENSOR): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_WINDOW_SENSORS): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Required(
                CONF_ROOM_TARGET,
                default=22.0
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5.0,
                    max=30.0,
                    step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Smart Offset Thermostat",
                "desc": "Выберите термостат, датчик температуры помещения и целевую температуру."
            }
        )


class SmartOffsetThermostatOptionsFlow(config_entries.OptionsFlow):
    """Поток опций для тонкой настройки."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Инициализация."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Первый (и единственный) шаг опций."""
        if user_input is not None:
            # Сохраняем только изменённые опции
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options

        # Обратная совместимость: старый CONF_WINDOW_SENSOR → новый CONF_WINDOW_SENSORS
        window_defaults = opts.get(CONF_WINDOW_SENSORS, [])
        if not window_defaults:
            old_single = opts.get(CONF_WINDOW_SENSOR)
            if old_single:
                window_defaults = [old_single] if isinstance(old_single, str) else old_single

        schema = vol.Schema({
            vol.Optional(
                CONF_WINDOW_SENSORS,
                default=window_defaults
            ): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            vol.Optional(
                CONF_INTERVAL_SEC,
                default=opts.get(CONF_INTERVAL_SEC, DEFAULTS[CONF_INTERVAL_SEC])
            ): NumberSelector(
                NumberSelectorConfig(min=60, max=1800, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(
                CONF_DEADBAND,
                default=opts.get(CONF_DEADBAND, DEFAULTS[CONF_DEADBAND])
            ): NumberSelector(
                NumberSelectorConfig(min=0.0, max=2.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_STEP_MAX,
                default=opts.get(CONF_STEP_MAX, DEFAULTS[CONF_STEP_MAX])
            ): NumberSelector(
                NumberSelectorConfig(min=0.1, max=5.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_STEP_MIN,
                default=opts.get(CONF_STEP_MIN, DEFAULTS[CONF_STEP_MIN])
            ): NumberSelector(
                NumberSelectorConfig(min=0.05, max=2.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_LEARN_RATE,
                default=opts.get(CONF_LEARN_RATE, DEFAULTS[CONF_LEARN_RATE])
            ): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.01, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TRV_MIN,
                default=opts.get(CONF_TRV_MIN, DEFAULTS[CONF_TRV_MIN])
            ): NumberSelector(
                NumberSelectorConfig(min=5.0, max=25.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_TRV_MAX,
                default=opts.get(CONF_TRV_MAX, DEFAULTS[CONF_TRV_MAX])
            ): NumberSelector(
                NumberSelectorConfig(min=15.0, max=35.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_COOLDOWN_SEC,
                default=opts.get(CONF_COOLDOWN_SEC, DEFAULTS[CONF_COOLDOWN_SEC])
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=3600, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(
                CONF_BOOST_DURATION_SEC,
                default=opts.get(CONF_BOOST_DURATION_SEC, DEFAULTS[CONF_BOOST_DURATION_SEC])
            ): NumberSelector(
                NumberSelectorConfig(min=30, max=7200, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(
                CONF_ENABLE_LEARNING,
                default=opts.get(CONF_ENABLE_LEARNING, DEFAULTS[CONF_ENABLE_LEARNING])
            ): BooleanSelector(),
            vol.Optional(
                CONF_STUCK_ENABLE,
                default=opts.get(CONF_STUCK_ENABLE, DEFAULTS[CONF_STUCK_ENABLE])
            ): BooleanSelector(),
            vol.Optional(
                CONF_STUCK_SECONDS,
                default=opts.get(CONF_STUCK_SECONDS, DEFAULTS[CONF_STUCK_SECONDS])
            ): NumberSelector(
                NumberSelectorConfig(min=300, max=86400, step=60, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(
                CONF_STUCK_MIN_DROP,
                default=opts.get(CONF_STUCK_MIN_DROP, DEFAULTS[CONF_STUCK_MIN_DROP])
            ): NumberSelector(
                NumberSelectorConfig(min=0.0, max=3.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_STUCK_STEP,
                default=opts.get(CONF_STUCK_STEP, DEFAULTS[CONF_STUCK_STEP])
            ): NumberSelector(
                NumberSelectorConfig(min=0.05, max=5.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "title": "Параметры управления",
                "desc": "Тонкая настройка поведения контроллера. Изменения применяются сразу."
            }
        )


@staticmethod
@callback
def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return SmartOffsetThermostatOptionsFlow(config_entry)