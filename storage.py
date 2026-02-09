from __future__ import annotations
from homeassistant.helpers.storage import Store
import asyncio
import time
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta


_STORAGE_VERSION = 1
_STORAGE_KEY = "smart_thermostat"
_MAX_HISTORY_DAYS = 7  # Храним историю только 7 дней
_MAX_HISTORY_ENTRIES = 1000  # Максимальное количество записей в истории
_SAVE_DEBOUNCE_SECONDS = 2.0  # Задержка перед сохранением


class OffsetStorage:
    def __init__(self, hass):
        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data: Dict[str, Dict[str, Any]] = {}
        self.hass = hass
        self._save_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._pending_save = False

    async def async_load(self):
        """Асинхронная загрузка данных."""
        async with self._lock:
            self._data = await self._store.async_load() or {}
            # Очистка устаревшей истории при загрузке
            self._cleanup_old_history()

    async def async_save(self, force: bool = False):
        """Асинхронное сохранение с debounce."""
        self._pending_save = True
        
        if force:
            # Принудительное сохранение
            if self._save_task:
                self._save_task.cancel()
                self._save_task = None
            await self._perform_save()
            return
        
        # Debounce сохранение
        if self._save_task and not self._save_task.done():
            return
        
        self._save_task = self.hass.async_create_task(self._debounced_save())

    async def _debounced_save(self):
        """Отложенное сохранение с debounce."""
        await asyncio.sleep(_SAVE_DEBOUNCE_SECONDS)
        
        if not self._pending_save:
            return
        
        async with self._lock:
            await self._perform_save()
        
        self._pending_save = False
        self._save_task = None

    async def _perform_save(self):
        """Выполнить фактическое сохранение."""
        try:
            await self._store.async_save(self._data)
        except Exception as e:
            # Логируем ошибку, но не падаем
            self.hass.components.persistent_notification.async_create(
                f"Ошибка сохранения настроек термостата: {e}",
                title="Smart Offset Thermostat",
                notification_id="smart_offset_storage_error"
            )

    def _cleanup_old_history(self):
        cutoff_time = time.time() - (_MAX_HISTORY_DAYS * 24 * 3600)

        for entry_id in list(self._data.keys()):
            # пропускаем отдельные ключи истории контроллера
            if isinstance(entry_id, str) and entry_id.startswith("history_"):
                continue

            entry_data = self._data.get(entry_id)
            if not isinstance(entry_data, dict):
                continue

            # offset_history
            history = entry_data.get("offset_history", [])
            if isinstance(history, list):
                # если ты уже хранишь timestamp как epoch — можно чистить по cutoff_time
                # history = [h for h in history if h.get("timestamp", 0) >= cutoff_time]
                if len(history) > _MAX_HISTORY_ENTRIES:
                    history = history[-_MAX_HISTORY_ENTRIES:]
                entry_data["offset_history"] = history

            # heating_rate_history
            hr = entry_data.get("heating_rate_history", [])
            if isinstance(hr, list) and len(hr) > 50:
                entry_data["heating_rate_history"] = hr[-50:]

            # overshoot_history
            oh = entry_data.get("overshoot_history", [])
            if isinstance(oh, list) and len(oh) > 50:
                entry_data["overshoot_history"] = oh[-50:]

    # ========== ОСНОВНЫЕ МЕТОДЫ ДЛЯ OFFSET ==========

    def get_offset(self, entry_id: str) -> float:
        """Получить текущее смещение."""
        try:
            return float(self._data.get(entry_id, {}).get("offset", 0.0))
        except (ValueError, TypeError):
            return 0.0

    async def set_offset(self, entry_id: str, offset: float, reason: str = "") -> None:
        """Установить смещение и сохранить время изменения."""
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            old_offset = entry_data.get("offset", 0.0)
            entry_data["offset"] = float(offset)
            entry_data["last_offset_change"] = self.hass.loop.time()
            entry_data["last_offset_value"] = float(old_offset)
            
            # Добавляем в историю
            self._add_offset_history(entry_id, offset, reason)
            
            # Увеличиваем счетчик изменений
            self._increment_offset_changes(entry_id)
        
        # Асинхронное сохранение
        await self.async_save()

    def get_last_offset_change(self, entry_id: str) -> Optional[float]:
        """Время последнего изменения offset (в секундах монотонных часов)."""
        return self._data.get(entry_id, {}).get("last_offset_change")

    def get_last_offset_value(self, entry_id: str) -> float:
        """Последнее значение offset до изменения."""
        try:
            return float(self._data.get(entry_id, {}).get("last_offset_value", 0.0))
        except (ValueError, TypeError):
            return 0.0

    def get_learning_stats(self, entry_id: str) -> Dict[str, Any]:
        """Получить статистику обучения."""
        entry_data = self._data.get(entry_id, {})
        return {
            "total_changes": entry_data.get("total_changes", 0),
            "last_change_time": entry_data.get("last_offset_change"),
            "current_offset": float(entry_data.get("offset", 0.0)),
            "initial_offset": float(entry_data.get("initial_offset", 0.0)),
            "offset_history_count": len(entry_data.get("offset_history", [])),
        }

    def get_history(self, entry_id: str) -> List[Dict[str, Any]]:
        """Получить историю для данного entry."""
        history_key = f"history_{entry_id}"
        history = self._data.get(history_key, [])
        
        # Очистка устаревших записей
        cutoff_time = time.time() - (_MAX_HISTORY_DAYS * 24 * 3600)
        cleaned_history = [
            entry for entry in history 
            if entry.get('time', 0) >= cutoff_time
        ]
        
        # Ограничение по количеству записей
        if len(cleaned_history) > _MAX_HISTORY_ENTRIES:
            cleaned_history = cleaned_history[-_MAX_HISTORY_ENTRIES:]
        
        return cleaned_history

    async def set_history(self, entry_id: str, history: List[Dict[str, Any]]) -> None:
        """Сохранить историю."""
        history_key = f"history_{entry_id}"
        
        async with self._lock:
            # Очистка устаревших записей перед сохранением
            cutoff_time = time.time() - (_MAX_HISTORY_DAYS * 24 * 3600)
            cleaned_history = [
                entry for entry in history 
                if entry.get('time', 0) >= cutoff_time
            ]
            
            # Ограничение по количеству записей
            if len(cleaned_history) > _MAX_HISTORY_ENTRIES:
                cleaned_history = cleaned_history[-_MAX_HISTORY_ENTRIES:]
            
            self._data[history_key] = cleaned_history
        
        await self.async_save()

    def _increment_offset_changes(self, entry_id: str):
        """Увеличить счетчик изменений offset."""
        entry_data = self._data.setdefault(entry_id, {})
        entry_data["total_changes"] = entry_data.get("total_changes", 0) + 1

    def _add_offset_history(self, entry_id: str, offset: float, reason: str = ""):
        """Добавить запись в историю изменений offset."""
        entry_data = self._data.setdefault(entry_id, {})
        history = entry_data.get("offset_history", [])
        
        history.append({
            "timestamp": self.hass.loop.time(),
            "offset": float(offset),
            "reason": reason
        })
        
        # Храним только последние 100 изменений
        if len(history) > 100:
            history = history[-100:]
        
        entry_data["offset_history"] = history

    # ========== МЕТОДЫ ДЛЯ HEATING_RATE ==========

    def get_heating_rate(self, entry_id: str) -> float:
        """Получить сохраненную скорость нагрева."""
        try:
            return float(self._data.get(entry_id, {}).get("heating_rate", 0.1))
        except (ValueError, TypeError):
            return 0.1

    async def set_heating_rate(self, entry_id: str, rate: float, reason: str = "") -> None:
        """Сохранить скорость нагрева."""
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            entry_data["heating_rate"] = float(rate)
            
            # Добавляем в историю
            self._add_heating_rate_history(entry_id, rate, reason)
        
        await self.async_save()

    def get_heating_rate_history(self, entry_id: str) -> List[Dict[str, Any]]:
        """Получить историю изменений скорости нагрева."""
        entry_data = self._data.get(entry_id, {})
        return entry_data.get("heating_rate_history", [])

    def _add_heating_rate_history(self, entry_id: str, rate: float, reason: str = ""):
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

    # ========== МЕТОДЫ ДЛЯ OVERSHOOT_COUNT ==========

    def get_overshoot_count(self, entry_id: str) -> int:
        """Получить счетчик перегрева."""
        try:
            return int(self._data.get(entry_id, {}).get("overshoot_count", 0))
        except (ValueError, TypeError):
            return 0

    async def set_overshoot_count(self, entry_id: str, count: int) -> None:
        """Установить счетчик перегрева."""
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            entry_data["overshoot_count"] = int(count)
        
        await self.async_save()

    async def increment_overshoot_count(self, entry_id: str) -> int:
        """Увеличить счетчик перегрева на 1 и вернуть новое значение."""
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            current = entry_data.get("overshoot_count", 0)
            new_count = current + 1
            entry_data["overshoot_count"] = new_count
        
        await self.async_save()
        return new_count

    async def reset_overshoot_count(self, entry_id: str) -> None:
        """Сбросить счетчик перегрева."""
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            entry_data["overshoot_count"] = 0
        
        await self.async_save()

    def get_overshoot_history(self, entry_id: str) -> List[Dict[str, Any]]:
        """Получить историю перегревов."""
        entry_data = self._data.get(entry_id, {})
        return entry_data.get("overshoot_history", [])

    async def add_overshoot_history(self, entry_id: str, temperature: float, overshoot: float, reason: str = "") -> None:
        """Добавить запись в историю перегревов."""
        async with self._lock:
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
        
        await self.async_save()

    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========

    async def cleanup_old_data(self, entry_id: str = None):
        """Очистка устаревших данных."""
        async with self._lock:
            if entry_id:
                # Очистка для конкретного entry
                if entry_id in self._data:
                    self._cleanup_entry_history(entry_id)
            else:
                # Очистка для всех entries
                for eid in list(self._data.keys()):
                    self._cleanup_entry_history(eid)
        
        await self.async_save(force=True)

    def _cleanup_entry_history(self, entry_id: str):
        """Очистка истории для конкретного entry."""
        if entry_id not in self._data:
            return
        
        entry_data = self._data[entry_id]
        cutoff_time = time.time() - (_MAX_HISTORY_DAYS * 24 * 3600)
        
        # Очистка offset_history
        if "offset_history" in entry_data:
            history = entry_data["offset_history"]
            cleaned = [h for h in history if h.get("timestamp", 0) >= cutoff_time]
            if len(cleaned) > 100:
                cleaned = cleaned[-100:]
            entry_data["offset_history"] = cleaned
        
        # Очистка heating_rate_history
        if "heating_rate_history" in entry_data:
            history = entry_data["heating_rate_history"]
            cleaned = [h for h in history if h.get("timestamp", 0) >= cutoff_time]
            if len(cleaned) > 50:
                cleaned = cleaned[-50:]
            entry_data["heating_rate_history"] = cleaned
        
        # Очистка overshoot_history
        if "overshoot_history" in entry_data:
            history = entry_data["overshoot_history"]
            cleaned = [h for h in history if h.get("timestamp", 0) >= cutoff_time]
            if len(cleaned) > 50:
                cleaned = cleaned[-50:]
            entry_data["overshoot_history"] = cleaned

    def get_all_entries(self) -> List[str]:
        """Получить список всех entry_id."""
        return [k for k in self._data.keys() if not k.startswith("history_")]

    async def remove_entry(self, entry_id: str) -> None:
        """Удалить данные для entry."""
        async with self._lock:
            if entry_id in self._data:
                del self._data[entry_id]
            # Также удаляем историю
            history_key = f"history_{entry_id}"
            if history_key in self._data:
                del self._data[history_key]
        
        await self.async_save(force=True)

    def get_minutes_per_degree(self, entry_id: str) -> float:
        try:
            return float(self._data.get(entry_id, {}).get("minutes_per_degree", 15.0))
        except (ValueError, TypeError):
            return 15.0

    async def set_minutes_per_degree(self, entry_id: str, mpd: float) -> None:
        async with self._lock:
            entry_data = self._data.setdefault(entry_id, {})
            entry_data["minutes_per_degree"] = float(mpd)
        await self.async_save()