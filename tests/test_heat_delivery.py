"""Диагностика «источник не даёт тепло» (heat_delivery, карта P0).

Регресс по дампу 02.11: детская 18:39–19:31 — клапан полностью открыт,
local 23.4 ≈ room 22.3, комната мёртвая (котёл не тянул), а пользователь
видел только «не греется». Гварды анти-ложных — из батла №2.

Запуск: python3 -m unittest tests.test_heat_delivery -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import heat_delivery_state  # noqa: E402


class HeatDeliveryFlowingTests(unittest.TestCase):
    def test_flowing_when_local_hot(self):
        """local ≥ room+1.5 → тепло реально идёт, даже при boost."""
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=0, heat_flowing=True, boosting=True,
                local_rising=False, since_step_up_sec=None,
            ),
            "flowing",
        )


class HeatDeliveryAbsentTests(unittest.TestCase):
    def test_absent_when_valve_open_long_no_heat(self):
        """Детская 02.11: открыт ≥10 мин, local ≈ room → absent."""
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=600, heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec=None,
            ),
            "absent",
        )

    def test_not_absent_before_threshold(self):
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=599, heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec=None,
            ),
            "unknown",
        )

    def test_not_absent_no_open_time(self):
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=None, heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec=None,
            ),
            "unknown",
        )


class HeatDeliveryGuardTests(unittest.TestCase):
    """Гварды анти-ложных (батл №2, круг 1 п.3)."""

    def test_boost_is_unknown(self):
        """Boost/cold_start активен — клапан открыт по определению,
        «нет тепла» в разгоне — ложная тревога."""
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=1200, heat_flowing=False, boosting=True,
                local_rising=False, since_step_up_sec=None,
            ),
            "unknown",
        )

    def test_local_rising_is_unknown(self):
        """Батарея разгоняется (local растёт) — не absent."""
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=1200, heat_flowing=False, boosting=False,
                local_rising=True, since_step_up_sec=None,
            ),
            "unknown",
        )

    def test_grace_after_step_up(self):
        """Первые ~15 мин после скачка цели вверх (утренний чугун)."""
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=1200, heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec=899,
            ),
            "unknown",
        )
        # grace истёк → absent
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec=1200, heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec=901,
            ),
            "absent",
        )

    def test_garbage_is_unknown(self):
        self.assertEqual(
            heat_delivery_state(
                valve_open_sec="abc", heat_flowing=False, boosting=False,
                local_rising=False, since_step_up_sec="x",
            ),
            "unknown",
        )


if __name__ == "__main__":
    unittest.main()
