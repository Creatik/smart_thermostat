"""Occupancy: person + свет/чайник — предпочтительнее жёстких часов."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import (  # noqa: E402
    merge_occupancy,
    state_means_activity,
    state_means_home,
)


class StateSemanticsTests(unittest.TestCase):
    def test_person_home_and_away(self):
        self.assertTrue(state_means_home("home"))
        self.assertTrue(state_means_home("Home"))
        self.assertFalse(state_means_home("not_home"))
        self.assertFalse(state_means_home("work"))
        self.assertFalse(state_means_home("Работа"))

    def test_activity_devices(self):
        self.assertTrue(state_means_activity("on"))
        self.assertTrue(state_means_activity("playing"))
        self.assertTrue(state_means_activity("detected"))
        self.assertFalse(state_means_activity("off"))
        self.assertFalse(state_means_activity("idle"))


class MergeOccupancyTests(unittest.TestCase):
    def test_no_sensors_assume_home(self):
        self.assertTrue(
            merge_occupancy(
                person_home=None,
                activity_on=False,
                activity_hold_active=False,
                has_person_sensors=False,
                has_activity_sensors=False,
            )
        )

    def test_person_only(self):
        self.assertTrue(
            merge_occupancy(
                person_home=True,
                activity_on=False,
                activity_hold_active=False,
                has_person_sensors=True,
                has_activity_sensors=False,
            )
        )
        self.assertFalse(
            merge_occupancy(
                person_home=False,
                activity_on=False,
                activity_hold_active=False,
                has_person_sensors=True,
                has_activity_sensors=False,
            )
        )

    def test_kettle_while_gps_still_at_work(self):
        """GPS ещё «работа», чайник on → дома (кто-то есть)."""
        self.assertTrue(
            merge_occupancy(
                person_home=False,
                activity_on=True,
                activity_hold_active=False,
                has_person_sensors=True,
                has_activity_sensors=True,
            )
        )

    def test_activity_hold_after_kettle_off(self):
        self.assertTrue(
            merge_occupancy(
                person_home=False,
                activity_on=False,
                activity_hold_active=True,
                has_person_sensors=True,
                has_activity_sensors=True,
            )
        )

    def test_all_away_no_activity(self):
        self.assertFalse(
            merge_occupancy(
                person_home=False,
                activity_on=False,
                activity_hold_active=False,
                has_person_sensors=True,
                has_activity_sensors=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
