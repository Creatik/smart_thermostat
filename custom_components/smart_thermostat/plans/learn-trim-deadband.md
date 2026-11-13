# Trim offset в deadband + единая ошибка

## Баг
1. Ветка trim `2 < |offset|` жила в `active_control` при `|e|≤deadband`,
   но тик всегда уходит в `deadband_hold` раньше → **мёртвый код**.
2. Aggressive decay считал `e = t_target − room`, active/hold —
   `t_effective − room` → при эко/погоде знаки могли расходиться.

## Фикс
- `offset_deadband_trim_adjustment` + `_handle_offset_trim_deadband` в hold
  (зона `2 < |offset| ≤ 3`, reason `offset_trim`).
- `|offset| > 3` по-прежнему только `offset_decay_aggressive`.
- Decay aggressive: `e = t_effective − room`.

## Спальня 01.11 ~22:00 — offset 2.546 «застыл»
`e=-0.6 > deadband` → active, не hold (trim молчит). Auto-tune
`learn_rate_slow=0.01` + инерционный перегрев при закрытом TRV дальше
душил rate. Поправка −0.006/тик ≈ час на шаг 0.1.

Добивка: `soft_against` → fast rate при |offset|≥2 и e против;
overshoot auto-tune только если TRV ещё «греет» (`_is_likely_heating`).
