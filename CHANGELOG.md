# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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