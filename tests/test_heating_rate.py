"""Проверка расчёта heating_rate (°C/мин)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    blend_minutes_per_degree,
    ema_heating_rate,
    heating_rate_sample,
    ttt_sample_mpd,
)


class HeatingRateSampleTests(unittest.TestCase):
    def test_normal_radiator_tick(self):
        # +0.1°C за 4 мин тика → 0.025 °C/мин (~40 мин/°C)
        r = heating_rate_sample(0.1, 4.0)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 0.025, places=6)

    def test_rejects_cooling(self):
        self.assertIsNone(heating_rate_sample(-0.1, 4.0))

    def test_rejects_tiny_dT(self):
        self.assertIsNone(heating_rate_sample(0.005, 4.0))

    def test_rejects_sensor_spike(self):
        # +1.5°C за 4 мин = 0.375 > MAX 0.25
        self.assertIsNone(heating_rate_sample(1.5, 4.0))

    def test_rejects_bad_dt(self):
        self.assertIsNone(heating_rate_sample(0.1, 0.1))
        self.assertIsNone(heating_rate_sample(0.1, 45.0))

    def test_gostinaia_like_slow(self):
        # эмпирика log_server: median ~0.024
        r = heating_rate_sample(0.1, 4.2)
        self.assertAlmostEqual(r, 0.1 / 4.2, places=5)

    def test_ema(self):
        # alpha=0.1: медленно тянется к sample
        v = ema_heating_rate(0.1, 0.025, 0.1)
        self.assertAlmostEqual(v, 0.1 * 0.025 + 0.9 * 0.1, places=6)


class ConsistencyTests(unittest.TestCase):
    def test_mpd_inverse(self):
        r = heating_rate_sample(0.2, 5.0)  # 0.04
        self.assertIsNotNone(r)
        mpd = 1.0 / r
        self.assertAlmostEqual(mpd, 25.0, places=5)


class TttSampleTests(unittest.TestCase):
    def test_rejects_zero_minute_episode(self):
        # детская 08.11: 0 мин, подъём зажали в 0.1° → mpd=2
        self.assertIsNone(
            ttt_sample_mpd(0.0, 0.1, min_minutes=5.0, min_rise=0.3, mpd_lo=8.0, mpd_hi=120.0)
        )

    def test_accepts_real_radiator(self):
        # 1.2° за 48 мин → 40 мин/°
        mpd = ttt_sample_mpd(48.0, 1.2, min_minutes=5.0, min_rise=0.3, mpd_lo=8.0, mpd_hi=120.0)
        self.assertAlmostEqual(mpd, 40.0, places=5)

    def test_poisoned_memory_snaps_to_rate(self):
        # память 2 мин/° и живой темп 0.036 °C/мин (~28 мин/°) — не усредняем с мусором
        blended = blend_minutes_per_degree(2.01, 0.036, mpd_min=8.0)
        self.assertAlmostEqual(blended, 1.0 / 0.036, places=3)

    def test_healthy_memory_blends(self):
        blended = blend_minutes_per_degree(40.0, 0.025, mpd_min=8.0, weight=0.15)
        sample = 1.0 / 0.025
        self.assertAlmostEqual(blended, 0.15 * sample + 0.85 * 40.0, places=4)


if __name__ == "__main__":
    unittest.main()
