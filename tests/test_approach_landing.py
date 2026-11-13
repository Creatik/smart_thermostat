"""Ранняя посадка TRV при горячем local на подходе к цели.

Факт (спальня 04.11): room≈23 / цель 23 / TRV 26 / local 24+ при
offset≈+2.8 → пик 24.3. Soft-landing PID не режет offset.

Запуск: python3 -m unittest tests.test_approach_landing -v
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
    approach_trv_ceiling,
    underheat_trv_floor,
)

DEADBAND = 0.5
LOCAL_MARGIN = 1.5
TRV_MARGIN = 0.8
BAND_TOP = DEADBAND + max(1.0, 2.0 * DEADBAND)  # 1.5


class ApproachTrvCeilingTests(unittest.TestCase):
    def test_spalnia_cuts_inflated_offset(self):
        """Спальня: e=0.3 / local≥цели / raw TRV 25.8 → потолок room+0.8."""
        t_target, t_room, offset, t_local = 23.0, 22.7, 2.8, 23.3
        e = t_target - t_room  # 0.3
        raw = t_target + offset  # 25.8
        # local−room=0.6 < 1.5, но local≥target → всё равно посадка
        ceil = approach_trv_ceiling(
            t_room,
            e,
            DEADBAND,
            t_local,
            t_target=t_target,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
        )
        self.assertIsNotNone(ceil)
        self.assertAlmostEqual(ceil, t_room + TRV_MARGIN, places=6)
        self.assertLess(ceil, raw - 1.0)

    def test_local_at_target_triggers_without_room_margin(self):
        """local уже на цели, room отстаёт — режем до добивания инерцией."""
        ceil = approach_trv_ceiling(
            22.5,
            error=0.5,
            deadband=DEADBAND,
            t_local=23.0,
            t_target=23.0,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
        )
        self.assertAlmostEqual(ceil, 22.5 + TRV_MARGIN, places=6)

    def test_no_cap_when_local_cold(self):
        """Батарея не греет (local≈room) — не режем, нужен разгон."""
        self.assertIsNone(
            approach_trv_ceiling(
                22.0, error=1.0, deadband=DEADBAND, t_local=22.2, local_margin=LOCAL_MARGIN
            )
        )

    def test_no_cap_when_far_from_target(self):
        """Далеко (e > band) — полная мощность, даже при горячем local."""
        self.assertIsNone(
            approach_trv_ceiling(
                21.0,
                error=2.0,
                deadband=DEADBAND,
                t_local=24.0,
                local_margin=LOCAL_MARGIN,
            )
        )
        self.assertGreater(2.0, BAND_TOP)

    def test_no_cap_on_overshoot_side(self):
        """Перелёт (e ≤ 0) — зона overshoot_trv_ceiling, не approach."""
        self.assertIsNone(
            approach_trv_ceiling(
                23.5, error=-0.5, deadband=DEADBAND, t_local=25.0, local_margin=LOCAL_MARGIN
            )
        )

    def test_no_cap_without_local_sensor(self):
        self.assertIsNone(
            approach_trv_ceiling(22.5, error=0.5, deadband=DEADBAND, t_local=None)
        )

    def test_respects_underheat_floor(self):
        """Потолок approach = underheat floor — инвариант недогрева жив."""
        t_room, e = 22.5, 0.5
        floor = underheat_trv_floor(t_room, e, DEADBAND, margin=TRV_MARGIN)
        ceil = approach_trv_ceiling(
            t_room,
            e,
            DEADBAND,
            t_local=24.5,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
        )
        self.assertIsNotNone(floor)
        self.assertIsNotNone(ceil)
        self.assertAlmostEqual(ceil, floor, places=6)

    def test_mid_band_with_hot_local(self):
        """e=1.0 в полосе (≤1.5) + local горячий → потолок есть."""
        ceil = approach_trv_ceiling(
            22.0,
            error=1.0,
            deadband=DEADBAND,
            t_local=24.0,
            local_margin=LOCAL_MARGIN,
            trv_margin=TRV_MARGIN,
        )
        self.assertAlmostEqual(ceil, 22.0 + TRV_MARGIN, places=6)


class ApproachOffsetTests(unittest.TestCase):
    def test_steps_down_toward_equilibrium(self):
        """offset +2.8 при room 22.7 / цель 23 → шаг к 0.5, не больше 0.3."""
        nxt = approach_offset_toward(2.8, 22.7, 23.0, trv_margin=0.8, max_step=0.3)
        self.assertAlmostEqual(nxt, 2.5, places=6)

    def test_does_not_raise_low_offset(self):
        self.assertAlmostEqual(
            approach_offset_toward(0.2, 22.7, 23.0, trv_margin=0.8, max_step=0.3),
            0.2,
            places=6,
        )

    def test_lands_on_implied_when_close(self):
        # implied = 22.7+0.8-23 = 0.5; 0.7 → 0.5
        self.assertAlmostEqual(
            approach_offset_toward(0.7, 22.7, 23.0, trv_margin=0.8, max_step=0.3),
            0.5,
            places=6,
        )


if __name__ == "__main__":
    unittest.main()
