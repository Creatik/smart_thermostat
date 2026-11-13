"""Подрезка offset в deadband + согласованность ошибки.

Запуск: python3 -m unittest tests.test_offset_trim -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import offset_deadband_trim_adjustment  # noqa: E402

RATE = 0.07


class OffsetTrimTests(unittest.TestCase):
    def test_trim_positive_offset_when_warm(self):
        """offset +2.5, e≤0 → уменьшаем (детская у цели)."""
        adj = offset_deadband_trim_adjustment(2.5, error=-0.1, learn_rate_slow=RATE)
        self.assertLess(adj, 0.0)
        self.assertAlmostEqual(adj, -RATE * min(0.5, 2.5 * 0.1), places=6)

    def test_trim_negative_offset_when_cold(self):
        adj = offset_deadband_trim_adjustment(-2.5, error=0.05, learn_rate_slow=RATE)
        self.assertGreater(adj, 0.0)

    def test_no_trim_below_soft_trigger(self):
        self.assertEqual(
            offset_deadband_trim_adjustment(1.9, error=-0.1, learn_rate_slow=RATE),
            0.0,
        )

    def test_no_trim_in_saturated_zone(self):
        """|offset|>3 — зона aggressive decay, trim молчит (без двойного удара)."""
        self.assertEqual(
            offset_deadband_trim_adjustment(3.5, error=-0.1, learn_rate_slow=RATE),
            0.0,
        )
        self.assertEqual(
            offset_deadband_trim_adjustment(-3.2, error=0.0, learn_rate_slow=RATE),
            0.0,
        )

    def test_no_trim_when_error_wrong_sign(self):
        """+offset при ещё холодной комнате (e>0.1) не режем."""
        self.assertEqual(
            offset_deadband_trim_adjustment(2.5, error=0.4, learn_rate_slow=RATE),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
