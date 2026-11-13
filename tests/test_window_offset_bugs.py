"""Дребезг окна и шаг насыщенного offset без просадки пола недогрева."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    commit_debounced_bool,
    saturated_offset_step,
    window_control_target,
    window_regime_offset,
)


class SaturatedStepTests(unittest.TestCase):
    def test_plus_six_while_slightly_cold_stops_at_floor(self):
        # e=0.4, margin=0.8 → пол offset = 0.4. Шаг 0.3 с +6.
        got = saturated_offset_step(
            6.0, 0.4, 0.5, saturated_trigger=3.0, underheat_margin=0.8, max_step=0.3
        )
        self.assertEqual(got, 5.7)

    def test_does_not_cut_below_underheat_floor(self):
        # уже у пола 0.4 — дальше вниз нельзя, комната ещё холоднее цели
        self.assertIsNone(
            saturated_offset_step(
                0.4, 0.4, 0.5, saturated_trigger=3.0, underheat_margin=0.8, max_step=0.3
            )
        )

    def test_no_step_outside_deadband(self):
        self.assertIsNone(
            saturated_offset_step(
                6.0, 1.2, 0.5, saturated_trigger=3.0, underheat_margin=0.8, max_step=0.3
            )
        )

    def test_negative_not_lifted_while_hot(self):
        self.assertIsNone(
            saturated_offset_step(
                -6.0, -0.4, 0.5, saturated_trigger=3.0, underheat_margin=0.8, max_step=0.3
            )
        )

    def test_negative_lifted_when_cold(self):
        self.assertEqual(
            saturated_offset_step(
                -6.0, 0.2, 0.5, saturated_trigger=3.0, underheat_margin=0.8, max_step=0.3
            ),
            -5.7,
        )


class WindowDebounceTests(unittest.TestCase):
    def test_flap_does_not_commit(self):
        committed, pending = commit_debounced_bool(True, False, None, 100.0, 8.0)
        self.assertFalse(committed)
        self.assertEqual(pending, 100.0)
        committed, pending = commit_debounced_bool(False, False, pending, 103.0, 45.0)
        self.assertFalse(committed)
        self.assertIsNone(pending)

    def test_stable_open_commits_fast(self):
        _, pending = commit_debounced_bool(True, False, None, 0.0, 8.0)
        committed, pending = commit_debounced_bool(True, False, pending, 8.0, 8.0)
        self.assertTrue(committed)
        self.assertIsNone(pending)

    def test_close_waits_longer(self):
        _, pending = commit_debounced_bool(False, True, None, 0.0, 45.0)
        committed, pending = commit_debounced_bool(False, True, pending, 8.0, 45.0)
        self.assertTrue(committed)
        self.assertEqual(pending, 0.0)
        committed, pending = commit_debounced_bool(False, True, pending, 45.0, 45.0)
        self.assertFalse(committed)
        self.assertIsNone(pending)


class WindowRegimeOffsetTests(unittest.TestCase):
    def test_first_open_does_not_jump(self):
        live, parked = window_regime_offset(-0.03, None)
        self.assertEqual(live, -0.03)
        self.assertEqual(parked, -0.03)

    def test_reopen_restores_open_offset(self):
        # закрытое −0.03 припарковано, входим в уже выученное открытое +2.4
        live, parked = window_regime_offset(-0.03, 2.4)
        self.assertEqual(live, 2.4)
        self.assertEqual(parked, -0.03)

    def test_close_restores_closed_offset(self):
        live, parked = window_regime_offset(4.2, -0.03)
        self.assertEqual(live, -0.03)
        self.assertEqual(parked, 4.2)

    def test_clamps_to_offset_band(self):
        live, parked = window_regime_offset(9.0, -9.0)
        self.assertEqual(live, -6.0)
        self.assertEqual(parked, 6.0)


class WindowEcoTargetTests(unittest.TestCase):
    def test_open_window_caps_at_eco(self):
        self.assertEqual(window_control_target(23.0, 19.0, True), 19.0)

    def test_night_schedule_stays_below_eco(self):
        self.assertEqual(window_control_target(18.0, 19.0, True), 18.0)

    def test_closed_window_keeps_comfort(self):
        self.assertEqual(window_control_target(23.0, 19.0, False), 23.0)


if __name__ == "__main__":
    unittest.main()
