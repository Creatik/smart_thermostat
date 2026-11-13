"""Скачок сырой цели расписания + антиспам arrival_warmup.

Запуск: python3 -m unittest tests.test_schedule_step -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import schedule_target_step, should_arrival_warmup  # noqa: E402


class ScheduleTargetStepTests(unittest.TestCase):
    def test_none_until_prev_known(self):
        self.assertIsNone(schedule_target_step(None, 23.0))

    def test_comfort_eco_jump(self):
        self.assertEqual(schedule_target_step(18.0, 23.0), "up")
        self.assertEqual(schedule_target_step(23.0, 18.0), "down")

    def test_weather_wobble_not_a_step(self):
        """Раньше t_effective 20.3→23.3 ложно триггерил boost."""
        self.assertIsNone(schedule_target_step(20.3, 21.1, threshold=2.0))
        self.assertIsNone(schedule_target_step(23.0, 23.4, threshold=2.0))

    def test_eco_occupancy_delta_ignored_if_raw_stable(self):
        # Сырая цель та же — step нет (эко ±3 живёт только в effective)
        self.assertIsNone(schedule_target_step(23.0, 23.0))


class ArrivalWarmupGuardTests(unittest.TestCase):
    def test_first_tick_no_warmup(self):
        self.assertFalse(
            should_arrival_warmup(
                present=True,
                prev_present=None,
                boost_active=False,
                error=2.0,
                deadband=0.3,
                now_mono=100.0,
                last_arrival_boost_mono=None,
                cooldown_sec=3600,
            )
        )

    def test_edge_underheat_fires(self):
        self.assertTrue(
            should_arrival_warmup(
                present=True,
                prev_present=False,
                boost_active=False,
                error=1.5,
                deadband=0.3,
                now_mono=100.0,
                last_arrival_boost_mono=None,
                cooldown_sec=3600,
            )
        )

    def test_already_at_target_skips(self):
        self.assertFalse(
            should_arrival_warmup(
                present=True,
                prev_present=False,
                boost_active=False,
                error=0.1,
                deadband=0.3,
                now_mono=100.0,
                last_arrival_boost_mono=None,
                cooldown_sec=3600,
            )
        )

    def test_cooldown_blocks_motion_spam(self):
        self.assertFalse(
            should_arrival_warmup(
                present=True,
                prev_present=False,
                boost_active=False,
                error=2.0,
                deadband=0.3,
                now_mono=2000.0,
                last_arrival_boost_mono=1000.0,
                cooldown_sec=3600,
            )
        )
        self.assertTrue(
            should_arrival_warmup(
                present=True,
                prev_present=False,
                boost_active=False,
                error=2.0,
                deadband=0.3,
                now_mono=5000.0,
                last_arrival_boost_mono=1000.0,
                cooldown_sec=3600,
            )
        )


if __name__ == "__main__":
    unittest.main()
