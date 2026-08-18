# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Split controller into modular architecture: `helpers.py`, `inputs.py`, `pid.py`, `feedforward.py`.
- Weather compensation (outdoor sensor / weather entity / forecast).
- Presence-based Eco mode (`eco_enable`, `eco_offset`).
- PID correction with anti-windup (`pid_kp`, `pid_ki`, `pid_kd`).
- Custom services `reset_offset` and `start_boost`.
- HACS repository layout (`custom_components/smart_thermostat/`), CI workflows, LICENSE, SECURITY, CHANGELOG.

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