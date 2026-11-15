"""Встроенное расписание ST: слоты comfort/sleep + лето + away."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    parse_schedule_hhmm,
    schedule_desired_mode,
    schedule_slot_mode,
    schedule_summer_blocks,
)


class ParseHhmmTests(unittest.TestCase):
    def test_normalizes(self):
        self.assertEqual(parse_schedule_hhmm("7:00:00", "07:00"), "07:00")
        self.assertEqual(parse_schedule_hhmm("21:00", "07:00"), "21:00")
        self.assertEqual(parse_schedule_hhmm("unknown", "21:00"), "21:00")


class SlotModeTests(unittest.TestCase):
    def test_day_comfort(self):
        self.assertEqual(schedule_slot_mode("10:00", "07:00", "21:00"), "comfort")
        self.assertEqual(schedule_slot_mode("07:00", "07:00", "21:00"), "comfort")
        self.assertEqual(schedule_slot_mode("20:59", "07:00", "21:00"), "comfort")

    def test_night_sleep(self):
        self.assertEqual(schedule_slot_mode("21:00", "07:00", "21:00"), "sleep")
        self.assertEqual(schedule_slot_mode("03:00", "07:00", "21:00"), "sleep")

    def test_overnight_comfort_wrap(self):
        # comfort 22:00, sleep 06:00 → ночной комфорт
        self.assertEqual(schedule_slot_mode("23:00", "22:00", "06:00"), "comfort")
        self.assertEqual(schedule_slot_mode("05:00", "22:00", "06:00"), "comfort")
        self.assertEqual(schedule_slot_mode("12:00", "22:00", "06:00"), "sleep")


class SummerGateTests(unittest.TestCase):
    def test_winter_never_blocks(self):
        self.assertFalse(schedule_summer_blocks(11, 25.0))

    def test_summer_warm_blocks(self):
        self.assertTrue(schedule_summer_blocks(7, 20.0))
        self.assertTrue(schedule_summer_blocks(7, None))

    def test_summer_cold_allows(self):
        self.assertFalse(schedule_summer_blocks(7, 10.0))


class DesiredModeTests(unittest.TestCase):
    def test_disabled(self):
        self.assertIsNone(
            schedule_desired_mode(
                schedule_enabled=False,
                away=False,
                now_hm="10:00",
                comfort_hm="07:00",
                sleep_hm="21:00",
                month=11,
                outdoor_temp=5.0,
            )
        )

    def test_away_eco(self):
        self.assertEqual(
            schedule_desired_mode(
                schedule_enabled=True,
                away=True,
                now_hm="10:00",
                comfort_hm="07:00",
                sleep_hm="21:00",
                month=11,
                outdoor_temp=5.0,
            ),
            "eco",
        )

    def test_comfort_and_sleep(self):
        self.assertEqual(
            schedule_desired_mode(
                schedule_enabled=True,
                away=False,
                now_hm="10:00",
                comfort_hm="07:00",
                sleep_hm="21:00",
                month=11,
                outdoor_temp=5.0,
            ),
            "comfort",
        )
        self.assertEqual(
            schedule_desired_mode(
                schedule_enabled=True,
                away=False,
                now_hm="22:00",
                comfort_hm="07:00",
                sleep_hm="21:00",
                month=11,
                outdoor_temp=5.0,
            ),
            "sleep",
        )


if __name__ == "__main__":
    unittest.main()
