# Меньше уставок на TRV

## Факт

15.11 после серии core restart: гостиная local→−0.01, спальня застыла и
позже тоже −0.01. В истории — 25.5↔26.0 каждую ~1 мин при `cooldown_sec=600`.
Детская (тот же Yandex YNDX-00518) жива. Спам `set_temperature` бьёт по
радио и батарее головы.

## Причина

Антиспам был только в active. Hold/approach/overshoot обходили cooldown.
`urgent` мог слать каждый тик. Mismatch ставил force каждый тик. После
смерти головы (−0.01) ST продолжал долбить уставки.

## Фикс

Единый `trv_write_gate` в `_set_trv_temperature`:

1. unavailable / dedup / **уже на устройстве** (`reported ± 0.3`)
2. cooldown для normal; **urgent ≥ 3 мин** (`TRV_URGENT_MIN_SEC`)
3. **≤ 12 команд/час** на голову (`TRV_MAX_WRITES_PER_HOUR`)
4. local stuck или raw ∉ 5…45 (−0.01) → probe раз в час
5. `forced` только off/exercise
6. mismatch: переотправка не чаще cooldown, без `last_set := reported`
