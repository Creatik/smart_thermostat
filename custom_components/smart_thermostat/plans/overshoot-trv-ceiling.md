# Потолок TRV при перелёте цели

Факт (спальня 01.11 ~21:30): room 23.6 / цель 23 / ST `idle` /
уставка TRV 25 (= target+offset≈2.55) / local 25.9. Батарея горячая.

Причина: при перелёте hold/active оставляли `target+offset`. Пока local
TRV > set клапан закрыт, но local остывает быстрее комнаты → set снова
выше local → клапан подоткрывается. Offset при этом не виноват.

Фикс: `overshoot_trv_ceiling` — при `error < −noise` уставка ≤ room−0.5.
В deadband — сразу `overshoot_close` к потолку; в active — cap без
ожидания cooldown. Offset не трогаем.
