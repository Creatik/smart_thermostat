# План: диагностика и исправление «smart_thermostat не закрывает клапан»

## Диагноз (подтверждён данными HA/Z2M)

1. **Offset прибит к −10.0°C** у всех трёх записей (детская `01KHC83P451RMXWZD74YKK4FJH`, гостиная `01KHGXG053D1MEBEZPQZ3F7WAB`, спальня `01KJ2GZFAX0SH8ZNKZYSS10EV3`), overshoot_count 134/334/335, total_changes до 13461 — предельный цикл обучения.
2. **Команды уставки до TRV доходят**: Z2M показывает `occupied_heating_setpoint: 8` (= trv_min при offset −10), local_temperature 20.7–23.9.
3. **Расхождение с физикой**: при уставке 8 и локальной 20–24 клапан должен быть закрыт (батареи холодные), но батареи горячие. У всех TRV `state: "ON"`, `system_mode: "off"` (команда HEAT не прилипает, контроллер не проверяет).
4. **Подозрение №1**: «Яндекс-эвристика» `_is_yandex_power_controlled()` принимает `switch.radiator_*_state` (Tuya/Moes TRV через Z2M) за питание Яндекса и сама включает его при переходе OFF→HEAT — у Tuya-TRV этот переключатель имеет другую семантику.
5. **Подозрение №2**: клапан механически не дожимается, либо комнаты греются от тёплых полов (кухня/ванная/коридор/лоджия) и стояков.

## Код интеграции — найденные дефекты

- [`_set_trv_temperature()`](../controller.py:421): оптимистичный `last_set`, dedup `abs(temp−last_set)<0.01` блокирует переотправку навсегда; нет сверки с фактической уставкой устройства.
- [`_handle_active_control()`](../controller.py:1053): `active_learning` с learn_rate_fast=0.5 даёт до ±2.5°C/тик — offset улетает в пол за 3 тика.
- [`_handle_stable_learning()`](../controller.py:750): самоссылочная формула `implied_offset = last_set − t_room ≈ e + offset`.
- [`PIDController.update()`](../pid.py:31): `i_limit=20` при выходе ±step_max — коррекция залипает на +1.0 даже при перегреве; внутри мёртвой зоны PID заморожен.
- [`_handle_deadband_hold()`](../controller.py:1009): вечный hold высокой уставки внутри мёртвой зоны.

## Фаза 0 — живой тест (руками пользователя, до правки кода)

1. В HA: открыть `climate.radiator_spalnia` — записать атрибуты `temperature`, `hvac_mode`, `current_temperature`; сравнить с сенсором `last_set` интеграции (расхождение = потерянные команды).
2. Выключить `switch.radiator_spalnia_state`, подождать 30 минут, потрогать батарею:
   - остыла → `state` держал клапан открытым → виновата Яндекс-эвристика;
   - горячая → клапан механически не держит / греют другие источники.
3. Включить `switch.radiator_spalnia_state` обратно.

## Фаза 1 — правки кода

1. **Верификация обратной связи** (controller.py): в каждом тике читать `climate_state.attributes["temperature"]`; при расхождении с `last_set` > 0.5°C — переотправить и залогировать warning; атрибут `trv_setpoint_sync`.
2. **Отключить Яндекс-эвристику**: `_is_yandex_power_controlled`/`_ensure_yandex_power` только при явной опции `power_switch_entity` (по умолчанию выключено).
3. **Скорость обучения**: cap ±0.3°C/тик на adjustment; MIN_OFFSET/MAX_OFFSET → ±6.
4. **stable_learn**: обучать только при устойчивой температуре и уставке, равной baseline; убрать самоссылку.
5. **PID**: `i_limit = step_max`; сброс интеграла при входе в мёртвую зону.
6. **deadband hold**: при t_room выше цели — плавно снижать уставку к baseline (шаг step_min за тик), не держать высокую.
7. **Диагностика** (атрибуты/сенсоры): `pid_i`, `baseline`, `t_trv_calculated`, `trv_reported_setpoint`.

## Фаза 2 — сброс выученного

- Кнопка «Сбросить смещение» (reset_offset) для всех трёх записей; обнулить overshoot_count (storage).

## Фаза 3 — критерии успеха

- Клапаны циклически закрываются (батареи чередуются горячий/холодный).
- Offset остаётся в ±3°C, total_changes растёт медленно.
- `trv_setpoint_sync` всегда ok; система_mode TRV соответствует командам.
