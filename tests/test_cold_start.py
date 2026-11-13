"""Холодный старт: рывок при большом недогреве + local TRV.

Запуск: python3 -m unittest tests.test_cold_start -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    local_is_stuck,
    should_cold_start_jerk,
    trv_heat_flowing,
    usable_trv_local,
    weather_suppressed,
)


class TrvHeatFlowTests(unittest.TestCase):
    def test_local_hotter_than_room(self):
        self.assertTrue(trv_heat_flowing(18.0, 20.0, margin=1.5))
        self.assertFalse(trv_heat_flowing(18.0, 19.0, margin=1.5))
        self.assertFalse(trv_heat_flowing(18.0, None))


class ColdStartJerkTests(unittest.TestCase):
    def test_jerk_when_room_far_below_and_trv_cold(self):
        """room 18 / цель 23 / local≈room → рывок."""
        self.assertTrue(
            should_cold_start_jerk(5.0, t_room=18.0, t_local=18.2, cold_error=2.0)
        )

    def test_no_jerk_when_gap_small(self):
        self.assertFalse(
            should_cold_start_jerk(1.5, t_room=21.5, t_local=21.5, cold_error=2.0)
        )

    def test_no_jerk_when_battery_already_hot(self):
        """Local уже ≫ room — тепло идёт, достаточно обычного контура."""
        self.assertFalse(
            should_cold_start_jerk(5.0, t_room=18.0, t_local=22.0, cold_error=2.0)
        )

    def test_no_jerk_when_already_at_max(self):
        """TRV уже на 30 — повторный рывок комнату не греет."""
        self.assertFalse(
            should_cold_start_jerk(
                2.5, t_room=22.3, t_local=None, cold_error=2.0, at_trv_max=True
            )
        )

    def test_jerk_when_local_missing_and_gap_large(self):
        """Мёртвый local не считается «тепло уже идёт»."""
        self.assertTrue(
            should_cold_start_jerk(
                2.7, t_room=20.3, t_local=None, cold_error=2.0, at_trv_max=False
            )
        )


class LocalAndWeatherTests(unittest.TestCase):
    def test_rejects_broken_local(self):
        self.assertIsNone(usable_trv_local(-0.01))
        self.assertIsNone(usable_trv_local(80.0))
        self.assertEqual(usable_trv_local(23.5), 23.5)
        self.assertEqual(usable_trv_local(17.9), 17.9)

    def test_flat_local_with_moving_setpoint_is_stuck(self):
        self.assertTrue(
            local_is_stuck(7200, 12.0, stuck_after_sec=7200, min_set_span=4.0)
        )

    def test_flat_hold_is_not_stuck(self):
        self.assertFalse(
            local_is_stuck(20000, 0.5, stuck_after_sec=7200, min_set_span=4.0)
        )

    def test_flat_while_commanded_far_above_is_stuck(self):
        """Уставка 30, local 23.5 полчаса не шевелится — датчик, не радиатор."""
        self.assertTrue(
            local_is_stuck(
                1800,
                0.0,
                stuck_after_sec=7200,
                min_set_span=4.0,
                commanded_above=True,
                command_stuck_sec=1800,
            )
        )
        self.assertFalse(
            local_is_stuck(
                600,
                0.0,
                stuck_after_sec=7200,
                min_set_span=4.0,
                commanded_above=True,
                command_stuck_sec=1800,
            )
        )

    def test_weather_latches_until_setpoint_releases(self):
        self.assertTrue(weather_suppressed(False, True, False))
        # сняли надбавку, set ещё у максимума — не включать снова
        self.assertTrue(weather_suppressed(True, False, False))
        self.assertFalse(weather_suppressed(True, False, True))
        # посадка уронила set, но комната уже у карточки — надбавку не возвращать
        self.assertTrue(weather_suppressed(True, False, True, room_short=False))
        self.assertFalse(weather_suppressed(True, False, True, room_short=True))


if __name__ == "__main__":
    unittest.main()
