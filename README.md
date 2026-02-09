# Smart Thermosmart — Home Assistant

Интеграция Home Assistant (domain: `smart_thermostat`) для “умного” управления TRV/термостатом по **одному или нескольким комнатным датчикам температуры**. Контроллер выставляет уставку через `climate.set_temperature`, поддерживает **окно открыто**, **Boost**, **самообучение offset** (включая stable learning), **затухание offset**, а также хранит историю/статистику в `storage`.

**Версия:** 1.2.0  
**IoT Class:** `local_polling`  
**Config Flow:** ✅ (настройка через UI)

---

## Возможности

- Усреднение температуры по нескольким `sensor.*` (комнатные датчики).
- Управление целевым `climate.*`:
  - периодический контроль с интервалом `interval_sec`
  - лимиты уставки `trv_min..trv_max`
  - ограничение шага изменения `step_min..step_max`
  - защита от “спама” установок через `cooldown_sec`
- Окна (`binary_sensor.*`):
  - при открытом окне выставляет `trv_min`
  - может отключать/замораживать обучение после длительного открытия (параметр `window_open_no_learn_min`)
- Boost:
  - на `boost_duration_sec` выставляет `trv_max`
- Самообучение offset:
  - активное и “stable learning” после `stable_learn_seconds`
  - затухание offset при простое (`offset_decay_rate/threshold`)
- Динамика/overshoot:
  - оценка скорости нагрева (EMA через `heating_alpha`)
  - учёт перегрева (`overshoot_threshold`) + история/счётчик
  - упрощённый TTT (`ttt_*`)
- Anti-stuck (опционально): “перегрето и не остывает” (`stuck_*`, `max_stuck_bias`).

---

## Установка

### Вручную (custom component)

1. Скопируйте папку интеграции в:
   `config/custom_components/smart_thermostat/`
2. Перезапустите Home Assistant.

### Через HACS (если репозиторий добавлен)

1. HACS → Integrations → Custom repositories → добавить репозиторий (Integration).
2. Установить интеграцию и перезапустить Home Assistant.

---

## Настройка (UI)

### Добавление интеграции

Settings → Devices & services → Add integration → **Smart Thermosmart**

Поля:
- **Thermostat (TRV)** (`climate_entity`) — один `climate.*`
- **Room temperature sensors** (`room_sensor_entities`) — один или несколько `sensor.*`
- **Window sensors (optional)** (`window_sensor_entities`) — один или несколько `binary_sensor.*`
- **Room target** (`room_target`) — целевая температура в °C

> Один и тот же `climate_entity` нельзя добавить дважды.

### Опции (Configure)

Settings → Devices & services → Smart Thermosmart → Configure

**Основные**
- `interval_sec` (240)
- `deadband` (0.2)
- `step_max` (1.0)
- `step_min` (0.5)
- `trv_min` (12.0)
- `trv_max` (30.0)
- `cooldown_sec` (600)

**Обучение**
- `enable_learning` (true)
- `learn_rate_fast` (0.5)
- `learn_rate_slow` (0.1)
- `min_offset_change` (0.2)
- `offset_learn_threshold` (0.5)
- `stable_learn_seconds` (900)
- `stable_learn_alpha` (0.25)
- `offset_decay_rate` (0.01)
- `offset_decay_threshold` (0.1)
- `no_learn_summer` (false)

**Окно**
- `window_sensor_entities` (список)
- `window_open_no_learn_min` (600)

**Boost**
- `boost_duration_sec` (300)

**Overshoot / динамика**
- `heating_alpha` (0.1)
- `overshoot_threshold` (0.5)
- `predict_minutes` (5)
- `ttt_alpha` (0.2)
- `ttt_soft_min` (10)

**Anti-stuck**
- `stuck_enable` (true)
- `stuck_seconds` (1800)
- `stuck_min_drop` (0.10)
- `stuck_step` (0.5)
- `max_stuck_bias` (4.0)

---

## Хранилище данных (storage)

Используется `homeassistant.helpers.storage.Store`:

- `key`: `smart_thermostat`
- `version`: 1

Данные по `entry_id`:
- `offset`, `last_offset_change`, `last_offset_value`, `total_changes`
- `offset_history` (до 100 записей)
- `heating_rate` + `heating_rate_history` (до 50)
- `overshoot_count` + `overshoot_history` (до 50)
- `minutes_per_degree`

Отдельная история контроллера:
- ключ `history_{entry_id}`

Ограничения:
- хранение истории: **до 7 дней**
- сохранение с debounce: ~2 секунды (есть `force=True`)

---

## Manifest / метаданные

- `domain`: `smart_thermostat`
- `name`: Smart Thermosmart
- `config_flow`: true
- `after_dependencies`: `recorder`
- `integration_type`: `hub`
- `iot_class`: `local_polling`
- `loggers`: `custom_components.smart_thermostat`
- `version`: 1.2.0

> Рекомендуется заполнить `documentation` и `issue_tracker` в `manifest.json` (сейчас пустые).

---

## Лицензия

Добавьте файл `LICENSE` (например, MIT).

---

## Поддержка / вклад

Если пришлёте `__init__.py`, основной контроллер/`climate.py` и список создаваемых entities/services — добавлю разделы **Entities**, **Services** и **Примеры автоматизаций** (Boost, reset offset, включение/выключение контроля).
