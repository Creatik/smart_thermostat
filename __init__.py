# Добавляем в __init__.py поддержку сервисов

from __future__ import annotations

import logging
from typing import Dict, Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN, PLATFORMS
from .storage import OffsetStorage
from .controller import SmartOffsetController


_LOGGER = logging.getLogger(__name__)

# CONFIG_SCHEMA нужен только если у вас есть YAML-конфигурация (редко для config entry only)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Схемы для сервисов
SERVICE_RESET_OFFSET_SCHEMA = vol.Schema({
    vol.Required("entry_id"): cv.string,
})

SERVICE_START_BOOST_SCHEMA = vol.Schema({
    vol.Required("entry_id"): cv.string,
    vol.Optional("duration"): cv.positive_int,
})


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Настройка компонента Smart Offset Thermostat (YAML часть, если есть)."""
    hass.data.setdefault(DOMAIN, {})
    
    # Регистрируем сервисы
    async def async_handle_reset_offset(call: ServiceCall) -> None:
        """Обработчик сервиса reset_offset."""
        entry_id = call.data["entry_id"]
        
        if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Конфигурационная запись %s не найдена", entry_id)
            return
        
        controller = hass.data[DOMAIN][entry_id]
        await controller.reset_offset()
        _LOGGER.info("Offset сброшен для записи %s", entry_id)
    
    async def async_handle_start_boost(call: ServiceCall) -> None:
        """Обработчик сервиса start_boost."""
        entry_id = call.data["entry_id"]
        duration = call.data.get("duration")
        
        if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
            _LOGGER.error("Конфигурационная запись %s не найдена", entry_id)
            return
        
        controller = hass.data[DOMAIN][entry_id]
        
        # Если указана длительность, временно меняем настройку
        if duration:
            original_duration = controller.opt("boost_duration_sec")
            controller.entry.options["boost_duration_sec"] = duration
            try:
                await controller.start_boost()
            finally:
                # Восстанавливаем оригинальную настройку
                if original_duration is not None:
                    controller.entry.options["boost_duration_sec"] = original_duration
                else:
                    controller.entry.options.pop("boost_duration_sec", None)
        else:
            await controller.start_boost()
        
        _LOGGER.info("Boost запущен для записи %s (длительность: %s сек)", 
                    entry_id, duration or "по умолчанию")
    
    # Регистрируем сервисы
    hass.services.async_register(
        DOMAIN,
        "reset_offset",
        async_handle_reset_offset,
        schema=SERVICE_RESET_OFFSET_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        "start_boost",
        async_handle_start_boost,
        schema=SERVICE_START_BOOST_SCHEMA,
    )
    
    _LOGGER.debug("Компонент Smart Offset Thermostat инициализирован, сервисы зарегистрированы")
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Миграция старых опций/данных в последний формат."""
    _LOGGER.debug("Миграция конфигурационной записи %s", entry.entry_id)
    
    if entry.version is None:
        current_version = 1
    else:
        current_version = entry.version

    options = dict(entry.options)
    data = dict(entry.data)
    changed = False

    # Миграция с window_sensor_entity -> window_sensor_entities (list)
    if "window_sensor_entities" not in options:
        old_key = "window_sensor_entity"
        if old_key in options and options.get(old_key):
            options["window_sensor_entities"] = [options[old_key]]
            options.pop(old_key, None)
            changed = True
            _LOGGER.debug("Мигрирован window_sensor_entity -> window_sensor_entities из options")
        elif old_key in data and data.get(old_key):
            options["window_sensor_entities"] = [data[old_key]]
            changed = True
            _LOGGER.debug("Мигрирован window_sensor_entity -> window_sensor_entities из data")

    # Очистка устаревшего ключа
    if "window_sensor_entity" in options:
        options.pop("window_sensor_entity", None)
        changed = True
        _LOGGER.debug("Удален устаревший ключ window_sensor_entity")

    # Миграция версий
    if current_version < 2:
        # Пример миграции для будущих версий
        # Добавляем новые параметры с дефолтными значениями
        if "enable_learning" not in options:
            options["enable_learning"] = True
            changed = True
        
        current_version = 2
        _LOGGER.debug("Мигрировано до версии 2")

    if changed:
        hass.config_entries.async_update_entry(
            entry, 
            options=options, 
            version=current_version
        )
        _LOGGER.info("Конфигурационная запись %s успешно мигрирована до версии %s", 
                    entry.entry_id, current_version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка Smart Offset Thermostat из конфигурационной записи."""
    _LOGGER.info("Настройка конфигурационной записи %s", entry.entry_id)
    
    hass.data.setdefault(DOMAIN, {})

    # Создаем или получаем хранилище
    storage_key = f"{DOMAIN}_storage"
    if storage_key not in hass.data:
        storage = OffsetStorage(hass)
        await storage.async_load()
        hass.data[storage_key] = storage
        _LOGGER.debug("Создано новое хранилище")
    else:
        storage = hass.data[storage_key]
        _LOGGER.debug("Используется существующее хранилище")

    # Создаем контроллер
    controller = SmartOffsetController(hass, entry, storage)
    hass.data[DOMAIN][entry.entry_id] = controller
    _LOGGER.debug("Создан контроллер для записи %s", entry.entry_id)

    try:
        # Настраиваем платформы (сенсоры и т.д.)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.debug("Платформы настроены: %s", PLATFORMS)
        
        # Запускаем контроллер
        await controller.async_start()
        _LOGGER.info("Контроллер для записи %s успешно запущен", entry.entry_id)
        
    except Exception as e:
        _LOGGER.error("Ошибка при настройке записи %s: %s", entry.entry_id, str(e), exc_info=True)
        
        # Очищаем данные в случае ошибки
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
        
        return False

    # Настраиваем слушатель для обновлений конфигурации
    entry.async_on_unload(
        entry.add_update_listener(async_update_options)
    )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Обработчик обновления опций конфигурационной записи."""
    _LOGGER.info("Обновление опций для записи %s", entry.entry_id)
    
    # Перезагружаем запись
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка конфигурационной записи."""
    _LOGGER.info("Выгрузка конфигурационной записи %s", entry.entry_id)
    
    entry_id = entry.entry_id
    
    # Останавливаем контроллер
    if entry_id in hass.data[DOMAIN]:
        controller = hass.data[DOMAIN].pop(entry_id)
        try:
            await controller.async_stop()
            _LOGGER.debug("Контроллер для записи %s остановлен", entry_id)
        except Exception as e:
            _LOGGER.error("Ошибка при остановке контроллера %s: %s", entry_id, str(e))

    # Выгружаем платформы
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if unload_ok:
            _LOGGER.info("Платформы для записи %s успешно выгружены", entry_id)
        else:
            _LOGGER.warning("Не удалось выгрузить все платформы для записи %s", entry_id)
        
        return unload_ok
        
    except Exception as e:
        _LOGGER.error("Ошибка при выгрузке записи %s: %s", entry_id, str(e), exc_info=True)
        return False


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Удаление конфигурационной записи."""
    _LOGGER.info("Удаление конфигурационной записи %s", entry.entry_id)
    
    entry_id = entry.entry_id
    
    # Удаляем данные из хранилища
    storage_key = f"{DOMAIN}_storage"
    if storage_key in hass.data:
        storage = hass.data[storage_key]
        try:
            await storage.remove_entry(entry_id)
            _LOGGER.debug("Данные записи %s удалены из хранилища", entry_id)
        except Exception as e:
            _LOGGER.error("Ошибка при удалении данных записи %s из хранилища: %s", entry_id, str(e))
    
    # Очищаем историю и другие данные
    if entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry_id, None)