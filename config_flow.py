from __future__ import annotations

import logging
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
from homeassistant.const import CONF_NAME

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
    DEFAULTS,
)


_LOGGER = logging.getLogger(__name__)


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
                    _LOGGER.warning(
                        "Попытка создать дублирующую конфигурацию: %s + %s",
                        user_input[CONF_CLIMATE], user_input[CONF_ROOM_SENSOR]
                    )
                    break

            if not errors:
                # Формируем красивое название
                climate_name = user_input[CONF_CLIMATE].split('.')[-1]
                sensor_name = user_input[CONF_ROOM_SENSOR].split('.')[-1]
                title = f"Smart Offset: {climate_name} ↔ {sensor_name}"
                
                _LOGGER.info(
                    "Создание новой конфигурации: %s (термостат: %s, датчик: %s)",
                    title, user_input[CONF_CLIMATE], user_input[CONF_ROOM_SENSOR]
                )
                
                return self.async_create_entry(title=title, data=user_input)

        # Схема для первого шага
        schema = vol.Schema({
            vol.Required(CONF_CLIMATE): EntitySelector(
                EntitySelectorConfig(
                    domain="climate",
                    multiple=False
                )
            ),
            vol.Required(CONF_ROOM_SENSOR): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    multiple=False
                )
            ),
            vol.Optional(CONF_WINDOW_SENSORS): EntitySelector(
                EntitySelectorConfig(
                    domain="binary_sensor",
                    multiple=True
                )
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
        _LOGGER.debug("Инициализация потока опций для записи %s", config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        """Первый (и единственный) шаг опций."""
        if user_input is not None:
            # Логируем изменения
            changed_keys = []
            for key, value in user_input.items():
                old_value = self.config_entry.options.get(key)
                if old_value != value:
                    changed_keys.append(key)
            
            if changed_keys:
                _LOGGER.info(
                    "Изменены опции для записи %s: %s",
                    self.config_entry.entry_id, changed_keys
                )
            
            # Сохраняем опции
            return self.async_create_entry(title="", data=user_input)

        # Получаем текущие опции
        opts = self.config_entry.options
        
        # Обратная совместимость: старый CONF_WINDOW_SENSOR → новый CONF_WINDOW_SENSORS
        window_defaults = opts.get(CONF_WINDOW_SENSORS, [])
        if not window_defaults:
            old_single = opts.get(CONF_WINDOW_SENSOR)
            if old_single:
                if isinstance(old_single, str):
                    window_defaults = [old_single]
                elif isinstance(old_single, list):
                    window_defaults = old_single
                _LOGGER.debug(
                    "Миграция window_sensor -> window_sensors для записи %s: %s",
                    self.config_entry.entry_id, window_defaults
                )

        # Вспомогательная функция для получения значения с fallback
        def get_option(key, default=None):
            """Получить значение опции с fallback на DEFAULTS."""
            value = opts.get(key)
            if value is not None:
                return value
            return DEFAULTS.get(key, default)

        # Схема для опций
        schema = vol.Schema({
            # Основные параметры
            vol.Optional(
                CONF_WINDOW_SENSORS,
                default=window_defaults
            ): EntitySelector(
                EntitySelectorConfig(domain="binary_sensor", multiple=True)
            ),
            
            vol.Optional(
                CONF_INTERVAL_SEC,
                default=get_option(CONF_INTERVAL_SEC)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=60, max=1800, step=10,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s"
                )
            ),
            
            vol.Optional(
                CONF_DEADBAND,
                default=get_option(CONF_DEADBAND)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0, max=2.0, step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_STEP_MAX,
                default=get_option(CONF_STEP_MAX)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.1, max=5.0, step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_STEP_MIN,
                default=get_option(CONF_STEP_MIN)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.05, max=2.0, step=0.05,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            # Параметры обучения
            vol.Optional(
                CONF_LEARN_RATE_FAST,
                default=get_option(CONF_LEARN_RATE_FAST)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0, max=1.0, step=0.01,
                    mode=NumberSelectorMode.BOX
                )
            ),
            
            vol.Optional(
                CONF_LEARN_RATE_SLOW,
                default=get_option(CONF_LEARN_RATE_SLOW)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0, max=1.0, step=0.01,
                    mode=NumberSelectorMode.BOX
                )
            ),
            
            vol.Optional(
                CONF_MIN_OFFSET_CHANGE,
                default=get_option(CONF_MIN_OFFSET_CHANGE)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0, max=1.0, step=0.05,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_ENABLE_LEARNING,
                default=get_option(CONF_ENABLE_LEARNING)
            ): BooleanSelector(),
            
            vol.Optional(
                CONF_NO_LEARN_SUMMER,
                default=get_option(CONF_NO_LEARN_SUMMER)
            ): BooleanSelector(),
            
            vol.Optional(
                CONF_WINDOW_OPEN_NO_LEARN_MIN,
                default=get_option(CONF_WINDOW_OPEN_NO_LEARN_MIN)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=1440, step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min"
                )
            ),
            
            # Параметры TRV
            vol.Optional(
                CONF_TRV_MIN,
                default=get_option(CONF_TRV_MIN)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5.0, max=25.0, step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_TRV_MAX,
                default=get_option(CONF_TRV_MAX)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=15.0, max=35.0, step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_COOLDOWN_SEC,
                default=get_option(CONF_COOLDOWN_SEC)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=3600, step=30,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s"
                )
            ),
            
            # Параметры boost
            vol.Optional(
                CONF_BOOST_DURATION_SEC,
                default=get_option(CONF_BOOST_DURATION_SEC)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=30, max=7200, step=30,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s"
                )
            ),
            
            # Параметры stuck detection
            vol.Optional(
                CONF_STUCK_ENABLE,
                default=get_option(CONF_STUCK_ENABLE)
            ): BooleanSelector(),
            
            vol.Optional(
                CONF_STUCK_SECONDS,
                default=get_option(CONF_STUCK_SECONDS)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=300, max=86400, step=60,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s"
                )
            ),
            
            vol.Optional(
                CONF_STUCK_MIN_DROP,
                default=get_option(CONF_STUCK_MIN_DROP)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.0, max=3.0, step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_STUCK_STEP,
                default=get_option(CONF_STUCK_STEP)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.05, max=5.0, step=0.05,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            # Параметры overshoot prevention
            vol.Optional(
                CONF_HEATING_ALPHA,
                default=get_option(CONF_HEATING_ALPHA)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.01, max=0.5, step=0.01,
                    mode=NumberSelectorMode.BOX
                )
            ),
            
            vol.Optional(
                CONF_OVERSHOOT_THRESHOLD,
                default=get_option(CONF_OVERSHOOT_THRESHOLD)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.1, max=2.0, step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°C"
                )
            ),
            
            vol.Optional(
                CONF_PREDICT_MINUTES,
                default=get_option(CONF_PREDICT_MINUTES)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=60, step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min"
                )
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
    """Получить поток опций для конфигурационной записи."""
    return SmartOffsetThermostatOptionsFlow(config_entry)