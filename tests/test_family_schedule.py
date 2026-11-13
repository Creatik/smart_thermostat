"""Семейное расписание = HA automation пользователя.

Будни: 23°C 05–07 и 18–23; иначе 18°C.
Выходные: 23°C 07–23; ночь 18°C.
Предпрогрев: за lead минут до начала комфортного слота.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    active_preheat_slot,
    in_night_no_learn_window,
    in_preheat_before_ready,
)

TZ = ZoneInfo("Europe/Moscow")


def _dt(y, m, d, hh, mi=0) -> datetime:
    return datetime(y, m, d, hh, mi, tzinfo=TZ)


class PreheatBeforeReadyTests(unittest.TestCase):
    def test_morning_workday_before_05(self):
        """К 05:00 lead=45 → окно 04:15–05:00."""
        self.assertTrue(in_preheat_before_ready(_dt(2026, 11, 2, 4, 30), "05:00", 45))
        self.assertFalse(in_preheat_before_ready(_dt(2026, 11, 2, 5, 0), "05:00", 45))
        self.assertFalse(in_preheat_before_ready(_dt(2026, 11, 2, 3, 0), "05:00", 45))

    def test_evening_before_18(self):
        self.assertTrue(in_preheat_before_ready(_dt(2026, 11, 2, 17, 30), "18:00", 45))
        self.assertFalse(in_preheat_before_ready(_dt(2026, 11, 2, 18, 0), "18:00", 45))


class WorkdayWeekendSlotsTests(unittest.TestCase):
    def test_workday_morning_and_evening(self):
        morning = active_preheat_slot(
            _dt(2026, 11, 2, 4, 30),  # пн
            "05:00",
            "18:00",
            45,
            is_workday=True,
            morning_ready_weekend="07:00",
        )
        self.assertEqual(morning, "morning")
        evening = active_preheat_slot(
            _dt(2026, 11, 2, 17, 20),
            "05:00",
            "18:00",
            45,
            is_workday=True,
            morning_ready_weekend="07:00",
        )
        self.assertEqual(evening, "evening")

    def test_weekend_morning_07_no_evening(self):
        """Выходные: комфорт с 07:00 — preheat к 07; вечерний слот выкл."""
        slot = active_preheat_slot(
            _dt(2026, 11, 1, 6, 30),  # вс
            "05:00",
            "18:00",
            45,
            is_workday=False,
            morning_ready_weekend="07:00",
        )
        self.assertEqual(slot, "morning")
        # в 04:30 на выходных ещё не греем (это будничное окно)
        early = active_preheat_slot(
            _dt(2026, 11, 1, 4, 30),
            "05:00",
            "18:00",
            45,
            is_workday=False,
            morning_ready_weekend="07:00",
        )
        self.assertIsNone(early)
        eve = active_preheat_slot(
            _dt(2026, 11, 1, 17, 30),
            "05:00",
            "18:00",
            45,
            is_workday=False,
            morning_ready_weekend="07:00",
        )
        self.assertIsNone(eve)

    def test_daytime_no_preheat(self):
        """День 07–18 на работе — греть нет смысла, preheat молчит."""
        self.assertIsNone(
            active_preheat_slot(
                _dt(2026, 11, 2, 12, 0),
                "05:00",
                "18:00",
                45,
                is_workday=True,
                morning_ready_weekend="07:00",
            )
        )


class NightNoLearnTests(unittest.TestCase):
    def test_matches_automation_23_to_05(self):
        """После 23:00→18 и до 05:00 — не учить (окна открыты)."""
        self.assertTrue(in_night_no_learn_window(_dt(2026, 11, 2, 23, 30), "23:00", "05:00"))
        self.assertTrue(in_night_no_learn_window(_dt(2026, 11, 2, 2, 0), "23:00", "05:00"))
        self.assertFalse(in_night_no_learn_window(_dt(2026, 11, 2, 5, 0), "23:00", "05:00"))
        self.assertFalse(in_night_no_learn_window(_dt(2026, 11, 2, 12, 0), "23:00", "05:00"))


if __name__ == "__main__":
    unittest.main()
