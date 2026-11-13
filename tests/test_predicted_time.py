"""Предсказанное время до цели.

Запуск: python3 -m unittest tests.test_predicted_time -v
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import predicted_minutes_to_target  # noqa: E402


class PredictedTimeTests(unittest.TestCase):
    def test_zero_when_at_or_above_target(self):
        self.assertEqual(predicted_minutes_to_target(-0.6, heating_rate=0.09), 0.0)
        self.assertEqual(predicted_minutes_to_target(0.0, heating_rate=0.09), 0.0)
        self.assertEqual(predicted_minutes_to_target(None, heating_rate=0.09), 0.0)

    def test_zero_inside_deadband(self):
        """Уже в deadband — «у цели», не error/rate=2.4 мин как раньше."""
        self.assertEqual(
            predicted_minutes_to_target(
                0.3, minutes_per_degree=2.1, heating_rate=0.127, deadband=0.3
            ),
            0.0,
        )

    def test_uses_mpd_not_inflated_rate_alone(self):
        """Детская: rate 0.127 завышен; mpd+rate → геометрическое, не 2 мин/°C."""
        # remaining = 1.5 - 0.3 = 1.2
        # mpd_ttt=20, mpd_rate=1/0.127≈7.87 → geo≈12.55 → 1.2*12.55≈15.1
        got = predicted_minutes_to_target(
            1.5, minutes_per_degree=20.0, heating_rate=0.127, deadband=0.3
        )
        naive_rate_only = round(1.2 / 0.127, 1)  # ~9.4
        mpd_only = round(1.2 * 20.0, 1)  # 24.0
        self.assertNotEqual(got, naive_rate_only)
        self.assertLess(got, mpd_only)
        self.assertGreater(got, naive_rate_only)
        self.assertAlmostEqual(got, round(1.2 * math.sqrt(20.0 * (1 / 0.127)), 1))

    def test_fallback_rate_when_no_mpd(self):
        # remaining 1.0, rate 0.05 → 20 мин
        self.assertEqual(
            predicted_minutes_to_target(1.5, heating_rate=0.05, deadband=0.5),
            20.0,
        )

    def test_fallback_mpd_when_no_rate(self):
        self.assertEqual(
            predicted_minutes_to_target(
                1.5, minutes_per_degree=30.0, deadband=0.5
            ),
            30.0,
        )

    def test_spalnia_desync_damped(self):
        """mpd=96 и rate=0.089 (≈11 мпд) — не брать крайности."""
        got = predicted_minutes_to_target(
            1.5, minutes_per_degree=96.0, heating_rate=0.089, deadband=0.5
        )
        geo = math.sqrt(96.0 * (1 / 0.089))
        self.assertAlmostEqual(got, round(1.0 * geo, 1))
        self.assertGreater(got, 20.0)
        self.assertLess(got, 96.0)


if __name__ == "__main__":
    unittest.main()
