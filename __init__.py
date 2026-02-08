from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .controller import SmartOffsetController
from .storage import OffsetStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = ["sensor", "button", "climate", "switch"]  # Убедитесь, что совпадает с const.py


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка интеграции из config entry."""
    _LOGGER.debug("async_setup_entry для %s", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})

    # Глобальное хранилище (одно на все записи)
    if "storage" not in hass.data[DOMAIN]:
        storage = OffsetStorage(hass)
        await storage.async_load()
        hass.data[DOMAIN]["storage"] = storage
        _LOGGER.debug("Создано и загружено глобальное хранилище")
    else:
        storage = hass.data[DOMAIN]["storage"]

    # Создаём контроллер для этой записи
    controller = SmartOffsetController(hass, entry, storage)
    hass.data[DOMAIN][entry.entry_id] = controller

    # Настраиваем платформы
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Запускаем контроллер
    await controller.async_start()

    # Слушатель обновления опций
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Интеграция Smart Offset Thermostat успешно настроена для %s", entry.entry_id)
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Обновление опций — перезагружаем запись."""
    _LOGGER.info("Опции обновлены для %s — перезагрузка", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка записи."""
    _LOGGER.info("Выгрузка записи %s", entry.entry_id)

    controller = hass.data[DOMAIN].get(entry.entry_id)
    if controller:
        await controller.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    # Выгружаем платформы
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    # Если это последняя запись — очищаем хранилище (опционально)
    if not hass.data[DOMAIN]:
        storage = hass.data[DOMAIN].pop("storage", None)
        if storage:
            # Не нужно явно сохранять — HA сам сохранит при shutdown
            _LOGGER.debug("Хранилище очищено (последняя запись выгружена)")

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Удаление записи — чистим данные в хранилище."""
    _LOGGER.info("Удаление записи %s", entry.entry_id)

    storage = hass.data[DOMAIN].get("storage")
    if storage:
        await storage.remove_entry(entry.entry_id)
        _LOGGER.debug("Данные записи %s удалены из хранилища", entry.entry_id)