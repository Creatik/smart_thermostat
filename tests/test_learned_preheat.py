"""Выученный график приходов → окно предпрогрева (lead 30/45/60)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    arrival_slot_kind,
    in_learned_preheat_window,
    median_int,
    predict_arrival_minutes,
)


class SlotKindTests(unittest.TestCase):
    def test_morning_evening(self):
        self.assertEqual(arrival_slot_kind(5 * 60 + 10), "morning")
        self.assertEqual(arrival_slot_kind(18 * 60), "evening")
        self.assertIsNone(arrival_slot_kind(2 * 60))  # ночь
        self.assertIsNone(arrival_slot_kind(13 * 60))  # обед


class PredictTests(unittest.TestCase):
    def test_median_weekday(self):
        # Приходы ~18:00 по понедельникам
        hist = [
            {"weekday": 0, "minutes": 17 * 60 + 50, "slot": "evening"},
            {"weekday": 0, "minutes": 18 * 60 + 5, "slot": "evening"},
            {"weekday": 0, "minutes": 18 * 60 + 0, "slot": "evening"},
            {"weekday": 1, "minutes": 19 * 60, "slot": "evening"},
        ]
        m = predict_arrival_minutes(hist, weekday=0, slot="evening", min_samples=3)
        self.assertEqual(m, 18 * 60)

    def test_fallback_all_days(self):
        hist = [
            {"weekday": 0, "minutes": 5 * 60, "slot": "morning"},
            {"weekday": 1, "minutes": 5 * 60 + 10, "slot": "morning"},
            {"weekday": 2, "minutes": 5 * 60 + 20, "slot": "morning"},
        ]
        # Среда ещё без своих 3 точек → медиана по всем утрам
        m = predict_arrival_minutes(hist, weekday=3, slot="morning", min_samples=3)
        self.assertEqual(m, 5 * 60 + 10)

    def test_not_enough_samples(self):
        hist = [
            {"weekday": 0, "minutes": 18 * 60, "slot": "evening"},
            {"weekday": 0, "minutes": 18 * 60 + 10, "slot": "evening"},
        ]
        self.assertIsNone(
            predict_arrival_minutes(hist, weekday=0, slot="evening", min_samples=3)
        )


class WindowTests(unittest.TestCase):
    def test_lead_45_before_18(self):
        ready = 18 * 60
        self.assertTrue(in_learned_preheat_window(17 * 60 + 20, ready, 45))
        self.assertFalse(in_learned_preheat_window(18 * 60, ready, 45))
        self.assertFalse(in_learned_preheat_window(16 * 60, ready, 45))

    def test_lead_30_vs_60(self):
        ready = 5 * 60
        self.assertFalse(in_learned_preheat_window(4 * 60 + 20, ready, 30))
        self.assertTrue(in_learned_preheat_window(4 * 60 + 35, ready, 30))
        self.assertTrue(in_learned_preheat_window(4 * 60 + 10, ready, 60))

    def test_median_helper(self):
        self.assertEqual(median_int([1, 3, 2]), 2)
        self.assertIsNone(median_int([]))


if __name__ == "__main__":
    unittest.main()
