# Встроенное расписание

График комфорт/сон/эко живёт **в storage записи** (`entry_id`), не в
`input_*` и не в захардкоженных `climate.radiator_*` конкретной семьи.

## Поведение

- Тумблер «расписание» на устройстве комнаты → `schedule.enabled`.
- Слоты comfort/sleep (Time-сущности) → `schedule.comfort` / `schedule.sleep`.
- Лето (июнь–август) и улица ≥ 18°C → график цель не двигает.
- Все настроенные `presence_entity` не home (без unknown) → пресет `eco`.
- Иначе дневная цель = `preset_comfort_temp`, ночная = `preset_sleep_temp`.
- Минутный poll + слушатели presence; apply до `_read_inputs`.

## Миграция со старых helper'ов

Ранние установки имели `input_boolean.st_det_schedule` и т.п.  
`SCHEDULE_HELPER_PREFIX_LEGACY` только для **одного** переноса в storage.
Новым пользователям helpers не нужны.

## Не складывать эко

`eco_delta` не применяется при пресете `eco`/`away`.
