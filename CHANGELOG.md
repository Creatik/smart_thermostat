# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-11-03

### Added
- Гвард «клапан без власти» (valve authority): обучение offset не гонит его
  к ±6, когда клапан уже полностью открыт и тепло не течёт (детская 02.11:
  1.8→+6 за час при мёртвой комнате), и не хоронит к −6 на эко-«перегреве»
  при закрытом клапане. `helpers.valve_learning_blocked` +
  `helpers.valve_ref_setpoint`, константа `VALVE_TRAVEL_MARGIN`.
- Сенсор диагностики `heat_delivery` (flowing/absent/unknown): честный ответ
  «почему не греется» — контур vs котёл/циркуляция. Гварды анти-ложных:
  boost, разгон local, grace 15 мин после скачка цели. `last_action =
  heat_source_absent` + warning не чаще раза в час.
- Сервис `clear_arrival_history` + авто-wipe истории приходов при смене
  `presence_entity` (миграция с motion на person.*: мусорные фронты
  уводят медиану слота learned_preheat).

### Fixed
- Детект скачка расписания по сырой цели (`t_target`), не `t_effective`:
  эко/погода давали ложные ±3°C, спам boost и сброс learn_freeze.
- `arrival_warmup` спам по motion кухни (9 раз/сутки): кулдаун 1 ч +
  boost только при реальном недогреве.

### Changed
- Обучение: `learn_rate_slow` восстановление, выход из насыщения
  (deep_against), pending-аккумулятор дробных поправок.
- Тесты: 103+ юнит-тестов (`tests/`), включая valve authority и
  heat_delivery от фактов дампов.

## [2.2.2] - 2026-10-13

### Added
- Планы работ: `plans/precision-improvements.md` (улучшения точности) и
  `plans/valve-not-closing-fix.md` (история борьбы с незакрывающимся клапаном).

### Changed
- `controller.py`: доработка цикла управления, обучения offset и удержания в мёртвой зоне.
- `storage.py`: расширение хранилища и историй (offset, preset, heating_rate).
- `__init__.py`, `climate.py`, `config_flow.py`, `const.py`, `inputs.py`, `pid.py`,
  `sensor.py`: сопутствующие правки и улучшения.

## [2.2.1] - 2026-08-18

### Fixed
- Ошибка «Entity None is neither a valid entity ID nor a valid UUID» при открытии настроек
  (сущности погоды/наружного датчика/влажности).
- Добавлены недостающие переводы опций в `ru.json` (`outdoor_sensor_entity` и др.).
- Переводы пресетов перенесены в ключ `state` (валидация hassfest).

## [2.2] - 2026-08-18

### Added
- Split controller into modular architecture: `helpers.py`, `inputs.py`, `pid.py`, `feedforward.py`.
- Weather compensation (outdoor sensor / weather entity / forecast).
- Presence-based Eco mode (`eco_enable`, `eco_offset`).
- PID correction with anti-windup (`pid_kp`, `pid_ki`, `pid_kd`).
- Custom services `reset_offset` and `start_boost`.
- HACS repository layout (`custom_components/smart_thermostat/`), CI workflows, LICENSE, SECURITY, CHANGELOG.
- Anti-debounce for TRV control: `min_on_sec` / `min_off_sec`.
- Predictive soft landing (overshoot cut-off) for gradual approach to target.
- Valve exercise (auto valve scroll): `valve_exercise_days` / `valve_exercise_sec`.
- **Presets** Comfort / Eco / Away / Sleep: configurable target temperatures
  (`preset_comfort_temp`, `preset_eco_temp`, `preset_away_temp`, `preset_sleep_temp`)
  selectable via the `preset_mode` property of the virtual thermostat.

### Fixed
- Undefined `DEFAULT_*` fallback constants causing potential `NameError`.
- Incorrect attribute keys (`climate`/`room_sensor`) in sensor `extra_state_attributes`.

## [1.2.0] - 2025-12-05

### Added
- Initial modular Home Assistant integration for smart TRV/thermostat control.
- Offset learning (active + stable), offset decay.
- Window open / Boost handling.
- Stuck / over-temperature detection.
- TTT (time-to-target) soft landing and heating-rate estimation.