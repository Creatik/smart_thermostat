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