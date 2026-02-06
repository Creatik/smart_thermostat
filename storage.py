from __future__ import annotations
from homeassistant.helpers.storage import Store
import time


_STORAGE_VERSION = 1
_STORAGE_KEY = "smart_offset_thermostat"


class OffsetStorage:
    def __init__(self, hass):
        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data = {}
        self._save_task = None
        self._lock = asyncio.Lock()
    
    async def _debounced_save(self):
        """Отложенное сохранение с debounce."""
        if self._save_task:
            self._save_task.cancel()
        self._save_task = self.hass.async_create_task(self._async_save_debounced())
    
    async def _async_save_debounced(self):
        await asyncio.sleep(1.0)  # Задержка 1 секунда
        async with self._lock:
            await self._store.async_save(self._data)


    async def async_load(self):
        self._data = await self._store.async_load() or {}


    async def async_save(self):
        await self._store.async_save(self._data)


    def get_offset(self, entry_id):
        """Получить текущее смещение."""
        return float(self._data.get(entry_id, {}).get("offset", 0.0))


    def set_offset(self, entry_id, offset):
        """Установить смещение и сохранить время изменения."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["offset"] = float(offset)
        entry_data["last_offset_change"] = self.hass.loop.time()
        entry_data["last_offset_value"] = float(offset)
            # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())
        
    def get_last_offset_change(self, entry_id: str) -> float | None:
        """Время последнего изменения offset (в секундах монотонных часов)."""
        return self._data.get(entry_id, {}).get("last_offset_change")


    def get_last_offset_value(self, entry_id: str) -> float:
        """Последнее значение offset до изменения."""
        return float(self._data.get(entry_id, {}).get("last_offset_value", 0.0))


    def get_learning_stats(self, entry_id: str) -> dict:
        """Получить статистику обучения."""
        entry_data = self._data.get(entry_id, {})
        return {
            "total_changes": entry_data.get("total_changes", 0),
            "last_change_time": entry_data.get("last_offset_change"),
            "current_offset": float(entry_data.get("offset", 0.0)),
            "initial_offset": float(entry_data.get("initial_offset", 0.0)),
            "offset_history": entry_data.get("offset_history", []),
        }


    def get_history(self, entry_id: str) -> list | None:
        """Получить историю для данного entry."""
        return self._data.get(f"history_{entry_id}")


    async def set_history(self, entry_id: str, history: list):
        """Сохранить историю."""
        self._data[f"history_{entry_id}"] = history
        await self.async_save()


    def increment_offset_changes(self, entry_id: str):
        """Увеличить счетчик изменений offset."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["total_changes"] = entry_data.get("total_changes", 0) + 1
        
    def add_offset_history(self, entry_id: str, offset: float, reason: str = ""):
        """Добавить запись в историю изменений offset."""
        entry_data = self._data.setdefault(entry_id, {})
        history = entry_data.get("offset_history", [])
        history.append({
            "timestamp": self.hass.loop.time(),
            "offset": offset,
            "reason": reason
        })
        # Храним только последние 100 изменений
        if len(history) > 100:
            history = history[-100:]
        entry_data["offset_history"] = history

    # МЕТОДЫ ДЛЯ HEATING_RATE
    def get_heating_rate(self, entry_id: str) -> float:
        """Получить сохраненную скорость нагрева."""
        entry_data = self._data.get(entry_id, {})
        return float(entry_data.get("heating_rate", 0.1))

    def set_heating_rate(self, entry_id: str, rate: float) -> None:
        """Сохранить скорость нагрева."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["heating_rate"] = float(rate)
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())

    def get_heating_rate_history(self, entry_id: str) -> list:
        """Получить историю изменений скорости нагрева."""
        entry_data = self._data.get(entry_id, {})
        return entry_data.get("heating_rate_history", [])

    def add_heating_rate_history(self, entry_id: str, rate: float, reason: str = ""):
        """Добавить запись в историю изменений скорости нагрева."""
        entry_data = self._data.setdefault(entry_id, {})
        history = entry_data.get("heating_rate_history", [])
        history.append({
            "timestamp": self.hass.loop.time(),
            "rate": float(rate),
            "reason": reason
        })
        # Храним только последние 50 изменений
        if len(history) > 50:
            history = history[-50:]
        entry_data["heating_rate_history"] = history
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())

    # МЕТОДЫ ДЛЯ OVERSHOOT_COUNT
    def get_overshoot_count(self, entry_id: str) -> int:
        """Получить счетчик перегрева."""
        entry_data = self._data.get(entry_id, {})
        return int(entry_data.get("overshoot_count", 0))

    def set_overshoot_count(self, entry_id: str, count: int) -> None:
        """Установить счетчик перегрева."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["overshoot_count"] = int(count)
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())

    def increment_overshoot_count(self, entry_id: str) -> int:
        """Увеличить счетчик перегрева на 1 и вернуть новое значение."""
        entry_data = self._data.setdefault(entry_id, {})
        current = entry_data.get("overshoot_count", 0)
        new_count = current + 1
        entry_data["overshoot_count"] = new_count
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())
        return new_count

    def reset_overshoot_count(self, entry_id: str) -> None:
        """Сбросить счетчик перегрева."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["overshoot_count"] = 0
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())

    def get_overshoot_history(self, entry_id: str) -> list:
        """Получить историю перегревов."""
        entry_data = self._data.get(entry_id, {})
        return entry_data.get("overshoot_history", [])

    def add_overshoot_history(self, entry_id: str, temperature: float, overshoot: float, reason: str = ""):
        """Добавить запись в историю перегревов."""
        entry_data = self._data.setdefault(entry_id, {})
        history = entry_data.get("overshoot_history", [])
        history.append({
            "timestamp": self.hass.loop.time(),
            "temperature": float(temperature),
            "overshoot": float(overshoot),
            "reason": reason
        })
        # Храним только последние 50 перегревов
        if len(history) > 50:
            history = history[-50:]
        entry_data["overshoot_history"] = history
        # Асинхронное сохранение
        self.hass.async_create_task(self.async_save())