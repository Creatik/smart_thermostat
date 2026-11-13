"""Физика радиатора: остывает медленно → недогрев хуже лёгкого перегрева.

Запуск: python3 -m unittest tests.test_radiator_inertia tests.test_soft_landing -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    overshoot_trv_ceiling,
    soft_landing_factor,
    underheat_trv_floor,
    valve_heat_demand,
)

DEADBAND = 0.5
MARGIN = 0.8


class ValveInertiaTests(unittest.TestCase):
    def test_underheat_opens_immediately(self):
        """Даже малый недогрев → открыть (не ждать +deadband)."""
        self.assertIs(valve_heat_demand(0.15, DEADBAND), True)
        self.assertIs(valve_heat_demand(DEADBAND + 0.1, DEADBAND), True)

    def test_overshoot_closes_early(self):
        """Перелёт цели → закрыть сразу: остаточное тепло ещё догреет."""
        self.assertIs(valve_heat_demand(-0.15, DEADBAND), False)
        self.assertIs(valve_heat_demand(-DEADBAND - 0.1, DEADBAND), False)

    def test_noise_band_no_chatter(self):
        self.assertIsNone(valve_heat_demand(0.0, DEADBAND))
        self.assertIsNone(valve_heat_demand(0.04, DEADBAND))
        self.assertIsNone(valve_heat_demand(-0.04, DEADBAND))


class UnderheatTrvFloorTests(unittest.TestCase):
    def test_floor_when_cold(self):
        """Цель выше комнаты: TRV не ниже room+margin (клапан физически откроется)."""
        floor = underheat_trv_floor(21.5, error=1.5, deadband=DEADBAND, margin=MARGIN)
        self.assertAlmostEqual(floor, 22.3, places=6)

    def test_floor_even_inside_deadband(self):
        """e=0.2 < deadband — всё равно пол: иначе TRV<room при hold."""
        floor = underheat_trv_floor(22.8, error=0.2, deadband=DEADBAND, margin=MARGIN)
        self.assertAlmostEqual(floor, 23.6, places=6)

    def test_no_floor_on_overshoot(self):
        self.assertIsNone(
            underheat_trv_floor(23.5, error=-0.5, deadband=DEADBAND, margin=MARGIN)
        )

    def test_gostinaia_style_negative_offset(self):
        """offset≈−3 при цели 23 / комнате 22.6 → сырой TRV=20 < room.

        Пол поднимает уставку выше комнаты — иначе under% и TRV<room как в логах.
        """
        t_target, t_room, offset = 23.0, 22.6, -3.0
        e = t_target - t_room
        raw = t_target + offset  # 20.0
        floor = underheat_trv_floor(t_room, e, DEADBAND, margin=MARGIN)
        self.assertIsNotNone(floor)
        self.assertLess(raw, t_room)
        self.assertGreaterEqual(max(raw, floor), t_room + MARGIN - 1e-9)


class SoftLandingVsUnderheatTests(unittest.TestCase):
    def test_floor_not_starving(self):
        """У края deadband множитель ≥ 0.3 — посадка не душит нагрев в ноль."""
        f = soft_landing_factor(DEADBAND, DEADBAND)
        self.assertGreaterEqual(f, 0.3 - 1e-9)

    def test_far_still_full_then_ease(self):
        self.assertEqual(soft_landing_factor(2.0, DEADBAND), 1.0)
        self.assertLess(soft_landing_factor(0.7, DEADBAND), 1.0)


class OvershootTrvCeilingTests(unittest.TestCase):
    CLOSE_MARGIN = 0.5

    def test_ceiling_when_room_above_target(self):
        """Спальня: room 23.6 / e=-0.6 → TRV ≤ 23.1, не target+offset=25."""
        ceil = overshoot_trv_ceiling(
            23.6, error=-0.6, deadband=DEADBAND, margin=self.CLOSE_MARGIN
        )
        self.assertAlmostEqual(ceil, 23.1, places=6)

    def test_no_ceiling_near_equilibrium(self):
        """У цели (|e|≈0) потолок не трогаем — нужен равновесный offset."""
        self.assertIsNone(
            overshoot_trv_ceiling(23.0, error=0.0, deadband=DEADBAND, margin=self.CLOSE_MARGIN)
        )
        self.assertIsNone(
            overshoot_trv_ceiling(23.0, error=-0.04, deadband=DEADBAND, margin=self.CLOSE_MARGIN)
        )

    def test_ceiling_inside_deadband_overshoot(self):
        """e=-0.2 < −noise при deadband=0.5 — уже закрывать уставку."""
        ceil = overshoot_trv_ceiling(
            23.2, error=-0.2, deadband=DEADBAND, margin=self.CLOSE_MARGIN
        )
        self.assertAlmostEqual(ceil, 22.7, places=6)

    def test_spalnia_hold_baseline_drops(self):
        """baseline=target+offset при перелёте режется потолком."""
        t_target, t_room, offset = 23.0, 23.6, 2.55
        e = t_target - t_room
        raw = t_target + offset  # 25.55
        ceil = overshoot_trv_ceiling(t_room, e, DEADBAND, margin=self.CLOSE_MARGIN)
        self.assertIsNotNone(ceil)
        self.assertGreater(raw, t_room)
        self.assertLessEqual(min(raw, ceil), t_room - self.CLOSE_MARGIN + 1e-9)


if __name__ == "__main__":
    unittest.main()
