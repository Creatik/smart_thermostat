"""Предиктивная ранняя посадка и evidence-гварды approach_trim.

Факт (спальня 04.11.2026): цель 23 весь день, утренний догон оставил
offset +4.7…+2.85. В 15:20 room 22.84 / local 23.3 / TRV 26.0 — посадка по
«горячему local» уже могла резать, но до 16:37 контур держал 26 и комната
доползла до пика 24.3 к 20:19. Здесь: второй признак посадки (rate/TTT —
«долетим за N минут») и гвард «комната реально растёт» для обучения вниз.

Запуск: python3 -m unittest tests.test_approach_predict -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    approach_offset_toward,
    approach_predict_landing,
    approach_trv_ceiling,
    local_is_rising,
    offset_write_within_budget,
    room_is_rising,
)

DEADBAND = 0.5
LOCAL_MARGIN = 1.5
TRV_MARGIN = 0.8
PREDICT_MAX_MIN = 12.0
RATE_MIN = 0.01
RISE_RATE_MIN = 0.005
RISE_DT_MIN = 1.0
BAND_TOP = DEADBAND + max(1.0, 2.0 * DEADBAND)  # 1.5

# Факт спальни 04.11 15:20 MSK
SP_ROOM, SP_TARGET, SP_LOCAL, SP_OFFSET = 22.84, 23.0, 23.3, 2.85


class RoomIsRisingTests(unittest.TestCase):
    """Evidence-гвард: посадка/trim только когда комната реально растёт."""

    def test_spalnia_slow_rise_is_rising(self):
        """0.04 °C за 4-минутный тик = 0.01 °C/мин — это рост, не шум."""
        self.assertTrue(
            room_is_rising(
                22.80, 0.0, 240.0, 22.84,
                rate_min=RISE_RATE_MIN, dt_min_lo=RISE_DT_MIN,
            )
        )

    def test_flat_room_is_not_rising(self):
        self.assertFalse(
            room_is_rising(22.84, 0.0, 240.0, 22.84, rate_min=RISE_RATE_MIN)
        )

    def test_falling_room_is_not_rising(self):
        """Остываем (окно/мороз) — учиться вниз нельзя: недогрев хуже перелёта."""
        self.assertFalse(
            room_is_rising(22.90, 0.0, 240.0, 22.70, rate_min=RISE_RATE_MIN)
        )

    def test_sensor_quant_on_short_interval_is_not_rising(self):
        """Квант 0.01 °C за 30 сек = 0.002 °C/мин < порога → не рост."""
        self.assertFalse(
            room_is_rising(22.84, 0.0, 30.0, 22.85, rate_min=RISE_RATE_MIN)
        )
        # тот же квант на интервале короче dt_min_lo — тоже не рост
        self.assertFalse(
            room_is_rising(
                22.84, 0.0, 20.0, 22.94,
                rate_min=RISE_RATE_MIN, dt_min_lo=RISE_DT_MIN,
            )
        )

    def test_no_previous_sample(self):
        self.assertFalse(room_is_rising(None, None, 240.0, 22.9))
        self.assertFalse(room_is_rising(22.8, None, 240.0, 22.9))

    def test_garbage_values(self):
        self.assertFalse(room_is_rising("unavailable", 0.0, 240.0, 22.9))


class ApproachPredictLandingTests(unittest.TestCase):
    """«Через N минут долетим» — второй признак ранней посадки."""

    def test_will_arrive_soon(self):
        """e=0.8, rate 0.05 (20 мин/°C) → 6 мин до deadband ≤ 12 → садимся."""
        self.assertTrue(
            approach_predict_landing(
                0.8, DEADBAND,
                heating_rate=0.05, room_rising=True, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )

    def test_inside_deadband_arrives_now(self):
        """e ≤ deadband → ETA 0 мин: мы уже у цели, держать TRV 26 незачем."""
        self.assertTrue(
            approach_predict_landing(
                0.2, DEADBAND,
                heating_rate=0.02, minutes_per_degree=40.0,
                room_rising=True, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )

    def test_too_far_by_rate(self):
        """Спальня 13:49: e=0.96 при rate 0.023 → ETA≈19 мин > 12 → ещё греем.

        Инерция после среза добивает ~12 минут хода, не 20: иначе посадка
        в километре от цели даёт недогрев (хуже перелёта).
        """
        self.assertFalse(
            approach_predict_landing(
                0.96, DEADBAND,
                heating_rate=0.023, minutes_per_degree=40.1,
                room_rising=True, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )
        # тот же e, но темп 0.08 °C/мин (12.5 мин/°C) → ETA≈6 мин: инерция добьёт
        self.assertTrue(
            approach_predict_landing(
                0.96, DEADBAND,
                heating_rate=0.08, minutes_per_degree=20.0,
                room_rising=True, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )

    def test_sun_on_room_sensor_is_not_cast_iron(self):
        """Комната растёт, батарея холодная и не теплеет — не садимся и не учим."""
        self.assertFalse(
            approach_predict_landing(
                0.3, DEADBAND,
                heating_rate=0.08, room_rising=True, local_rising=False,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )
        self.assertFalse(local_is_rising(22.3, 0.0, 240.0, None))
        self.assertFalse(local_is_rising(22.3, 0.0, 240.0, 22.3))

    def test_battery_warming_counts(self):
        """local 21.4 → 21.8 за 4 мин — тепло пошло в клапан, это не солнце."""
        self.assertTrue(
            local_is_rising(21.4, 0.0, 240.0, 21.8, rate_min=RISE_RATE_MIN)
        )

    def test_requires_rising_room(self):
        """rate из storage — EMA и живёт часами: без факта роста не садимся."""
        self.assertFalse(
            approach_predict_landing(
                0.3, DEADBAND,
                heating_rate=0.08, room_rising=False, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
            )
        )

    def test_requires_learned_rate(self):
        for rate in (None, 0.0, 0.005):
            self.assertFalse(
                approach_predict_landing(
                    0.3, DEADBAND,
                    heating_rate=rate, room_rising=True, local_rising=True,
                    predict_max_min=PREDICT_MAX_MIN, rate_min=RATE_MIN,
                )
            )

    def test_disabled_by_default_predict_zero(self):
        """predict_max_min=0 — ветка выключена (поведение до патча)."""
        self.assertFalse(
            approach_predict_landing(
                0.3, DEADBAND,
                heating_rate=0.08, room_rising=True, local_rising=True,
                predict_max_min=0.0,
            )
        )

    def test_garbage_rate_is_ignored(self):
        self.assertFalse(
            approach_predict_landing(
                0.3, DEADBAND,
                heating_rate="unavailable", room_rising=True, local_rising=True,
                predict_max_min=PREDICT_MAX_MIN,
            )
        )


class ApproachCeilingPredictiveTests(unittest.TestCase):
    """Потолок TRV: горячий local ИЛИ прогноз долёта."""

    def _ceil(self, **kw):
        base = dict(
            t_target=SP_TARGET,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
            heating_rate=0.05,
            room_rising=True,
            local_rising=True,
            predict_max_min=PREDICT_MAX_MIN,
            rate_min=RATE_MIN,
        )
        base.update(kw)
        return approach_trv_ceiling(
            base.pop("t_room", SP_ROOM),
            base.pop("error", 0.16),
            base.pop("deadband", DEADBAND),
            base.pop("t_local", 22.9),  # local холодный: 22.9 < target, −room 0.06
            **base,
        )

    def test_cold_local_but_predicted_landing(self):
        """local ещё ниже порога «горячо», но сам растёт и ETA близко → потолок."""
        ceil = self._ceil()
        self.assertIsNotNone(ceil)
        self.assertAlmostEqual(ceil, SP_ROOM + TRV_MARGIN, places=6)

    def test_sun_with_flat_local_does_not_land(self):
        """Комната растёт, local стоит — солнце, не чугун. Потолка нет."""
        self.assertIsNone(self._ceil(local_rising=False))

    def test_no_predict_when_room_not_rising(self):
        self.assertIsNone(self._ceil(room_rising=False))

    def test_no_predict_when_far_from_target(self):
        """e=2.0 > полосы 1.5 — полная мощность, прогноз не имеет права резать."""
        self.assertGreater(2.0, BAND_TOP)
        self.assertIsNone(self._ceil(error=2.0, t_room=21.0))

    def test_no_predict_on_overshoot_side(self):
        """e ≤ 0 — зона overshoot_trv_ceiling, не approach."""
        self.assertIsNone(self._ceil(error=-0.3, t_room=23.3))

    def test_predict_needs_a_local_sensor(self):
        """Нет local — рост комнаты не доказывает запас в батарее."""
        self.assertIsNone(self._ceil(t_local=None, local_rising=True))

    def test_hot_local_wins_even_when_not_rising(self):
        """Горячая батарея (local ≥ цели) — посадка и без роста комнаты."""
        ceil = self._ceil(t_local=23.4, room_rising=False, heating_rate=None)
        self.assertAlmostEqual(ceil, SP_ROOM + TRV_MARGIN, places=6)

    def test_predict_disabled_keeps_old_behaviour(self):
        """predict_max_min=0 + холодный local → None (как до патча)."""
        self.assertIsNone(self._ceil(predict_max_min=0.0))


class SpalniaReplayTests(unittest.TestCase):
    """Прогон факта спальни 04.11: что бы изменилось в 15:20."""

    def test_baseline_would_be_cut_by_more_than_two_degrees(self):
        e = SP_TARGET - SP_ROOM  # 0.16
        baseline = SP_TARGET + SP_OFFSET  # 25.85 → на TRV стояло 26.0
        ceil = approach_trv_ceiling(
            SP_ROOM, e, DEADBAND, SP_LOCAL,
            t_target=SP_TARGET,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
            heating_rate=0.05,
            room_rising=True,
            predict_max_min=PREDICT_MAX_MIN,
        )
        self.assertIsNotNone(ceil)
        self.assertGreater(baseline - ceil, 2.0)
        # потолок = пол недогрева: инвариант «TRV ≥ room+margin при e>0» жив
        self.assertAlmostEqual(ceil, SP_ROOM + TRV_MARGIN, places=6)

    def test_offset_steps_down_toward_landing_equilibrium(self):
        """implied = room+margin−target = 0.64; шаг ≤ max_offset_step."""
        nxt = approach_offset_toward(
            SP_OFFSET, SP_ROOM, SP_TARGET,
            trv_margin=TRV_MARGIN, max_step=0.3, min_change=0.1,
        )
        self.assertAlmostEqual(nxt, SP_OFFSET - 0.3, places=6)
        self.assertGreater(nxt, SP_ROOM + TRV_MARGIN - SP_TARGET - 1e-9)

    def test_zero_budget_blocks_offset_write(self):
        """Бюджет тика выбран другим писателем → offset не двигаем (инвариант 3)."""
        self.assertAlmostEqual(
            approach_offset_toward(
                SP_OFFSET, SP_ROOM, SP_TARGET,
                trv_margin=TRV_MARGIN, max_step=0.0, min_change=0.1,
            ),
            SP_OFFSET,
            places=6,
        )


class OffsetBudgetTests(unittest.TestCase):
    def test_aggressive_decay_waits_when_trim_spent_the_step(self):
        """approach_trim уже −0.3 → decay ×0.92 в этом тике молчит."""
        proposed = 4.4 * (1.0 - 0.08)
        self.assertIsNone(
            offset_write_within_budget(
                4.4, proposed, spent=0.3, max_step=0.3, min_change=0.1
            )
        )

    def test_decay_alone_is_capped_at_max_step(self):
        """4.4 × 0.92 хотел бы −0.35; за тик не больше 0.3 → 4.1."""
        proposed = 4.4 * (1.0 - 0.08)
        got = offset_write_within_budget(
            4.4, proposed, spent=0.0, max_step=0.3, min_change=0.1
        )
        self.assertAlmostEqual(got, 4.1, places=6)


if __name__ == "__main__":
    unittest.main()
