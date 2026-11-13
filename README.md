<!-- markdownlint-disable MD041 -->
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/Creatik/smart_thermostat)](https://github.com/Creatik/smart_thermostat/releases/latest)
[![License: MIT](https://img.shields.io/github/license/Creatik/smart_thermostat)](LICENSE)

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
  - активное обучение + «stable learning» + soft-landing (`approach_trim`);
  - **valve authority** — не гонит offset к ±6, когда клапан уже на упоре и тепла нет;
  - затухание смещения со временем (`offset_decay_rate/threshold`);
  - TTT (time-to-target) мягкая посадка и оценка скорости нагрева.
- **Диагностика `heat_delivery`** — flowing / absent / unknown: контур vs котёл/циркуляция.
- **Погодная компенсация** — при похолодании автоматически агрессивнее греет:
  источник — датчик наружной температуры / `weather.*` / прогноз.
- **Эко-режим по присутствию** — если никого нет дома, уставка снижается на `eco_offset`.
- **Пресеты** — быстрый выбор целевой температуры: **Comfort / Eco / Away / Sleep**
  (переключаются через `preset_mode` виртуального термостата, каждая со своей уставкой).
- **Расписание comfort/sleep** — time-сущности на устройстве комнаты.
- **PID-регулирование** — `pid_kp/ki/kd` с анти-виндиапом вместо простого P-контроля.
- **Окна** — при открытом окне уставка → `trv_min`, обучение приостанавливается.
- **Boost** — временный форсированный нагрев до `trv_max` (в т.ч. cold-start после эко).
- **Anti-stuck** — детектор «перегрето и не остывает».
- **Виртуальный термостат** — полноценная `climate.*` сущность для дашбордов и HomeKit.
- **Всё настраивается через UI**, без YAML (короткая форма + advanced).

---

## 📦 Установка

### Marketplace (Home Assistant 2026.11+)

С 2026.11 HACS встроен в HA как **Marketplace** (`Settings → Marketplace`).

1. **Settings → Marketplace** → **Add from link** (справа сверху).
2. Укажите репозиторий: `https://github.com/Creatik/smart_thermostat`
   (или `Creatik/smart_thermostat`).
3. При запросе подключите GitHub (нужно для custom repositories).
4. Тип: **Integration**, если HA не определит сам → **Add**.
5. Откройте карточку репозитория → **Download / Install**, затем
   **перезапустите Home Assistant**.

Обновления: Marketplace проверяет custom-репозитории roughly раз в 48 ч
(при подключённом GitHub), либо обновите вручную на странице репозитория.

### HACS (Home Assistant ≤ 2026.10)

1. HACS → меню (⋮) → **Custom repositories**.
2. URL: `https://github.com/Creatik/smart_thermostat`, тип **Integration** → **Add**.
3. Найдите **Smart Thermostat** → **Download**, затем перезапустите Home Assistant.

### Вручную

Скопируйте папку `custom_components/smart_thermostat/` в
`config/custom_components/` и перезапустите Home Assistant.

---

## ⚙️ Настройка (UI)

**Быстрый старт (3 шага):**

1. **Settings → Devices & Services → Add Integration → Smart Thermostat**
2. Выберите **термостат на радиаторе**, **датчики комнаты** и желаемую температуру.
3. Готово — умная подстройка (offset, прогрев после эко, PID) работает на дефолтах.

Опционально при установке: датчики окна.

> Один и тот же `climate_entity` нельзя добавить дважды.

### Configure — основные настройки

Форма короткая и понятная:

- переключатель клапана (если есть у TRV), окна, улица / погода;
- «кто дома» + экономия без людей;
- температуры режимов Комфорт / Эко / Вдали / Сон;
- автоподстройка, форсаж, прокрутка клапана.

Пресеты на виртуальном `climate.*`: `preset_mode` = `none` / `comfort` / `eco` / `away` / `sleep`.

### Расширенные настройки

Включите **«Показать расширенные настройки»** — откроется второй шаг с PID,
скоростями обучения, stuck, TTT и т.д. Обычно менять не нужно: интеллект
в контроллере и `DEFAULTS`, а не в десятках ручек.

---

## 🖥️ Сущности

- **climate.*** — виртуальный термостат.
- **button.*** — сброс накопленного offset.
- **switch.*** — Boost вкл/выкл.
- **time.*** — слоты расписания комфорт / сон.
- **sensor.*** — отладка: `error`, `offset`, `target_trv`, `last_set`, `last_action(_text)`,
  `change_count`, `window_state`, `boost_*`, `control_paused`, `heating_rate`, `predicted_time`,
  `device_temperature`, `heat_delivery`.

---

## 🛠️ Сервисы

| Сервис | Описание |
|---|---|
| `smart_thermostat.reset_offset` | Сброс накопленного смещения (`entry_id`). |
| `smart_thermostat.start_boost` | Включить Boost на `duration` сек (опционально). |
| `smart_thermostat.clear_arrival_history` | Очистить историю приходов (для learned preheat). |

---

## 🔧 Разработка

```
custom_components/smart_thermostat/
├── __init__.py     # настройка/выгрузка записи + сервисы
├── config_flow.py  # UI-конфигурация (simple + advanced)
├── const.py        # константы и дефолты
├── controller.py   # оркестратор (тик, режимы, обучение)
├── helpers.py      # чистые хелперы (valve authority, heat delivery, …)
├── inputs.py       # датакласс входных данных
├── pid.py          # PIDController
├── feedforward.py  # эко/погодная компенсация
├── sensor.py / climate.py / button.py / switch.py / time.py
├── storage.py      # хранение offset/истории
└── plans/          # разборы и планы улучшений
```

Запуск проверок: `hassfest` и `hacs/action` через `.github/workflows/`.
Юнит-тесты: `python -m pytest tests/`.

---

## 📜 Лицензия

MIT. Подробнее — в файле [LICENSE](LICENSE).