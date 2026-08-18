## v2.2.1 — Исправления стабильности и перевода

Патч-релиз поверх v2.2. Исправлены проблемы, возникавшие при настройке через UI.

### 🐛 Исправлено
- **Ошибка при открытии настроек** «Entity None is neither a valid entity ID nor a valid
  UUID» — для сущностей погоды, наружного датчика и влажности значение по умолчанию
  теперь корректно обрабатывается (`vol.UNDEFINED` вместо `None`).
- **Отсутствующие переводы** опций в русской локализации: добавлены `outdoor_sensor_entity`,
  `min_on_sec`, `min_off_sec`, `valve_exercise_days`, `valve_exercise_sec`,
  `weather_base_temp`, `weather_max_comp`, `eco_enable`, `cooldown_reduction_factor`.
- **Валидация hassfest**: переводы пресетов перенесены в корректный ключ `state`.

### 📦 Установка / обновление
- Обновление через HACS → **Smart Thermostat** → **Update**, затем перезапуск Home Assistant.

### 🔧 Прочее
- Автоматическая публикация релиза: собирается `smart_thermostat.zip`, описание берётся
  из `RELEASE_NOTES.md`, релиз публикуется сразу (без ручного редактирования).