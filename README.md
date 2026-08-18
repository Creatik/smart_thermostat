<!-- markdownlint-disable MD041 -->
<img src="https://img.shields.io/badge/HACS-Custom-orange.svg">
<img src="https://img.shields.io/github/v/release/Creatik/smart_thermostat">
<img src="https://img.shields.io/github/license/Creatik/smart_thermostat">

# Smart Thermostat — Home Assistant

Интеграция Home Assistant (domain: `smart_thermostat`) для «умного» управления
TRV/термостатом по **одному или нескольким комнатным датчикам температуры**.

Контроллер выставляет уставку через `climate.set_temperature`, автоматически
**обучает температурное смещение** реального термостата, поддерживает
**окно открыто**, **Boost**, **эко-режим по присутствию**, **погодную
компенсацию** и **PID-регулирование**.

> **Принцип:** интеграция не управляет клапаном напрямую и не зависит от
> вендора — она лишь корректирует целевую температуру физического `climate.*`,
> поэтому совместима с широким кругом термостатов (в т.ч. Yandex/Alika).

---

## ✨ Возможности

- **Автообучение offset** — адаптивная компенсация тепловой инерции и неточности датчика:
  - активное обучение + «stable learning»;
  - затухание смещения со временем (`offset_decay_rate/threshold`);
  - TTT (time-to-target) мягкая посадка и оценка скорости нагрева.
- **Погодная компенсация** — при похолодании автоматически агрессивнее греет:
  источник — датчик наружной температуры / `weather.*` / прогноз.
- **Эко-режим по присутствию** — если никого нет дома, уставка снижается на `eco_offset`.
- **Пресеты** — быстрый выбор целевой температуры: **Comfort / Eco / Away / Sleep**
  (переключаются через `preset_mode` виртуального термостата, каждая со своей уставкой).
- **PID-регулирование** — `pid_kp/ki/kd` с анти-виндиапом вместо простого P-контроля.
- **Окна** — при открытом окне уставка → `trv_min`, обучение приостанавливается.
- **Boost** — временный форсированный нагрев до `trv_max`.
- **Anti-stuck** — детектор «перегрето и не остывает».
- **Виртуальный термостат** — полноценная `climate.*` сущность для дашбордов и HomeKit.
- **Всё настраивается через UI**, без YAML.

---

## 📦 Установка

### Через HACS (рекомендуется)

1. HACS → **Integrations** → меню (⋮) → **Custom repositories**.
2. Добавьте: `https://github.com/Creatik/smart_thermostat`
3. Категория: **Integration**.
4. Нажмите **Install** и перезапустите Home Assistant.

### Вручную

Скопируйте папку `custom_components/smart_thermostat/` в
`config/custom_components/` и перезапустите Home Assistant.

---

## ⚙️ Настройка (UI)

**Settings → Devices & Services → Add Integration → Smart Thermostat**

Обязательные поля:
- **Термостат** (`climate_entity`) — один `climate.*`.
- **Датчики температуры помещения** (`room_sensor_entities`) — один или несколько `sensor.*`.
- **Целевая температура** (`room_target`) — в °C.

Опционально: датчики окна (`binary_sensor.*`).

> Один и тот же `climate_entity` нельзя добавить дважды.

### Параметры (Configure)

- **Управление**: интервал, мёртвая зона, шаг `step_min/step_max`, пределы `trv_min/trv_max`, `cooldown`.
- **Обучение**: `enable_learning`, `learn_rate_fast/slow`, `min_offset_change`,
  `no_learn_summer`, `stable_learn_*`, `offset_decay_*`, `offset_learn_threshold`.
- **Окна / Boost**: `window_sensor_entities`, `window_open_no_learn_min`, `boost_duration_sec`.
- **Stuck**: `stuck_enable`, `stuck_seconds`, `stuck_min_drop`, `stuck_step`, `max_stuck_bias`.
- **Динамика**: `heating_alpha`, `overshoot_threshold`, `predict_minutes`, `ttt_*`.
- **Умные фичи**:
  - `outdoor_sensor_entity` / `weather_entity` — источник наружной температуры;
  - `weather_base_temp`, `weather_max_comp` — настройка погодной компенсации;
  - `presence_entity` — датчики присутствия (Person / binary_sensor);
  - `eco_enable`, `eco_offset` — эко-режим при отсутствии людей;
  - `predictive_factor` — влияние холода на компенсацию;
  - `pid_kp/ki/kd` — коэффициенты PID.
- **Пресеты**: `preset_comfort_temp`, `preset_eco_temp`, `preset_away_temp`,
  `preset_sleep_temp` — целевые температуры каждого пресета (в °C). Активный пресет
  выбирается свойством `preset_mode` виртуального термостата (`none` — ручная уставка,
  `comfort`, `eco`, `away`, `sleep`).

---

## 🖥️ Сущности

- **climate.*** — виртуальный термостат.
- **button.*** — сброс накопленного offset.
- **switch.*** — Boost вкл/выкл.
- **sensor.*** — отладка: `error`, `offset`, `target_trv`, `last_set`, `last_action(_text)`,
  `change_count`, `window_state`, `boost_*`, `control_paused`, `heating_rate`, `predicted_time`,
  `device_temperature`.

---

## 🛠️ Сервисы

| Сервис | Описание |
|---|---|
| `smart_thermostat.reset_offset` | Сброс накопленного смещения (`entry_id`). |
| `smart_thermostat.start_boost` | Включить Boost на `duration` сек (опционально). |

---

## 🔧 Разработка

```
custom_components/smart_thermostat/
├── __init__.py     # настройка/выгрузка записи + сервисы
├── config_flow.py  # UI-конфигурация
├── const.py        # константы и дефолты
├── controller.py   # оркестратор (тик, режимы, обучение)
├── helpers.py      # чистые хелперы
├── inputs.py       # датаклacc входных данных
├── pid.py          # PIDController
├── feedforward.py  # эко/погодная компенсация
├── sensor.py / climate.py / button.py / switch.py
└── storage.py      # хранение offset/истории
```

Запуск проверок: `hassfest` и `hacs/action` через `.github/workflows/`.

---

## 📜 Лицензия

MIT. Подробнее — в файле [LICENSE](LICENSE).