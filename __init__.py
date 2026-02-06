from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .storage import OffsetStorage
from .controller import SmartOffsetController

# CONFIG_SCHEMA нужен только если у вас есть YAML-конфигурация (редко для config entry only)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# Глобальное хранилище (одно на всю интеграцию, загружается один раз)
STORAGE: OffsetStorage | None = None


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Smart Offset Thermostat component (YAML part, if any)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old options/data to the latest format."""
    if entry.version is None:
        current_version = 1
    else:
        current_version = entry.version

    options = dict(entry.options)
    data = dict(entry.data)
    changed = False

    # Migrate from single window_sensor_entity -> window_sensor_entities (list)
    if "window_sensor_entities" not in options:
        old_key = "window_sensor_entity"
        if old_key in options and options.get(old_key):
            options["window_sensor_entities"] = [options[old_key]]
            options.pop(old_key, None)
            changed = True
        elif old_key in data and data.get(old_key):
            options["window_sensor_entities"] = [data[old_key]]
            changed = True

    # Cleanup legacy key
    if "window_sensor_entity" in options:
        options.pop("window_sensor_entity", None)
        changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, options=options, version=current_version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart Offset Thermostat from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    global STORAGE
    if STORAGE is None:
        STORAGE = OffsetStorage(hass)
        await STORAGE.async_load()  # ← await здесь разрешён, т.к. внутри async def

    controller = SmartOffsetController(hass, entry, STORAGE)
    hass.data[DOMAIN][entry.entry_id] = controller

    # Forward to platforms (sensor, climate и т.д.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Запуск контроллера (он сам асинхронный)
    await controller.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if entry.entry_id in hass.data[DOMAIN]:
        controller = hass.data[DOMAIN].pop(entry.entry_id)
        await controller.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok