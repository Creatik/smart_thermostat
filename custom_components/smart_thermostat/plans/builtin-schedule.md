# Встроенное расписание

Внешняя HA automation «Управление Smart Thermostat по времени и дням»
дублировала то, что уже готовили UI-слоты (`time.py` / `…_schedule`).

## Поведение

- Тумблер `input_boolean.st_*_schedule` выкл → цель не трогаем.
- Лето (июнь–август) и улица ≥ 18°C → график молчит.
- Оба person не home (без unknown) → пресет `eco`.
- Иначе по `…_comfort` / `…_sleep`: дневная цель = `preset_comfort_temp`,
  ночная = `preset_sleep_temp` (через room_target, пресет `none`).
- Минутный poll + слушатели слотов/presence; в тике apply до `_read_inputs`.

## Не складывать эко

`eco_delta` не применяется, если уже пресет `eco`/`away` — иначе
19 + (−3) ≈ 16°C.

## После выката

Automation `1770185490237` выключить/удалить. Comfort в опциях дома
поставить **23**, если раньше automation писала 23 при пресете 22.
