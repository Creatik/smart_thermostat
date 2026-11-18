"""Антиспам записи уставки на TRV (plans/trv-setpoint-spam.md)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import trv_write_gate  # noqa: E402


class TestTrvWriteGate(unittest.TestCase):
    def test_unavailable(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="unavailable",
                last_set=20.0,
                desired=22.0,
                now=1000.0,
                last_change=0.0,
                cooldown_sec=600.0,
            ),
            "trv_unavailable",
        )

    def test_no_change(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=22.0,
                now=1000.0,
                last_change=0.0,
                cooldown_sec=600.0,
            ),
            "no_change",
        )

    def test_already_on_device(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=1000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                reported_setpoint=26.2,
                reported_eps=0.3,
            ),
            "already_on_device",
        )

    def test_cooldown_blocks_normal(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=23.0,
                now=1000.0,
                last_change=900.0,
                cooldown_sec=600.0,
            ),
            "cooldown",
        )

    def test_urgent_has_min_floor(self):
        """Недогрев не каждый тик — пол urgent_min_sec."""
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=1000.0,
                last_change=950.0,
                cooldown_sec=600.0,
                urgency="urgent",
                urgent_min_sec=180.0,
            ),
            "cooldown",
        )

    def test_urgent_ok_after_floor(self):
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=1200.0,
                last_change=1000.0,
                cooldown_sec=600.0,
                urgency="urgent",
                urgent_min_sec=180.0,
            )
        )

    def test_stuck_blocks_even_urgent(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=1000.0,
                last_change=900.0,
                cooldown_sec=600.0,
                local_stuck=True,
                stuck_resend_sec=3600.0,
                urgency="urgent",
            ),
            "trv_stuck_backoff",
        )

    def test_stuck_allows_after_hour(self):
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=5000.0,
                last_change=1000.0,
                cooldown_sec=600.0,
                local_stuck=True,
                stuck_resend_sec=3600.0,
                urgency="urgent",
            )
        )

    def test_hour_budget(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=26.0,
                now=5000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                urgency="urgent",
                writes_last_hour=12,
                max_writes_per_hour=12,
            ),
            "rate_limited",
        )

    def test_forced_respects_budget(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=30.0,
                now=5000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                urgency="forced",
                writes_last_hour=12,
                max_writes_per_hour=12,
            ),
            "rate_limited",
        )

    def test_forced_respects_stuck(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=30.0,
                now=1000.0,
                last_change=900.0,
                cooldown_sec=600.0,
                local_stuck=True,
                stuck_resend_sec=3600.0,
                urgency="forced",
            ),
            "trv_stuck_backoff",
        )

    def test_forced_skips_cooldown_when_budget_ok(self):
        """Прокрутка не ждёт 10 минут, но и не долбит мёртвую голову."""
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=30.0,
                now=1000.0,
                last_change=999.0,
                cooldown_sec=600.0,
                urgency="forced",
                writes_last_hour=1,
                max_writes_per_hour=12,
            )
        )

    def test_shutdown_closes_despite_budget_and_stuck(self):
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=5.0,
                now=1000.0,
                last_change=999.0,
                cooldown_sec=600.0,
                local_stuck=True,
                stuck_resend_sec=3600.0,
                urgency="shutdown",
                writes_last_hour=99,
                max_writes_per_hour=12,
            )
        )

    def test_shutdown_does_not_repeat(self):
        self.assertEqual(
            trv_write_gate(
                climate_state="off",
                last_set=5.0,
                desired=5.0,
                now=1000.0,
                last_change=999.0,
                cooldown_sec=600.0,
                urgency="shutdown",
            ),
            "no_change",
        )

    def test_rail_already_open_is_not_rewritten(self):
        """29.5 при максимуме 30 — клапан уже открыт, шток не трогаем."""
        self.assertEqual(
            trv_write_gate(
                climate_state="heat",
                last_set=28.0,
                desired=30.0,
                now=5000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                reported_setpoint=29.5,
                reported_eps=0.3,
                saturate_hi=30.0,
                saturate_margin=1.0,
            ),
            "already_on_device",
        )

    def test_lost_command_is_not_deduped(self):
        """Память 30, на голове после батареек 19 — команду надо повторить."""
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=30.0,
                desired=30.0,
                now=5000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                reported_setpoint=19.0,
                reported_eps=0.3,
                urgency="urgent",
                urgent_min_sec=180.0,
            )
        )

    def test_rail_does_not_hide_a_real_open(self):
        """Голова на 22, нужно 30 — это ход клапана, его надо послать."""
        self.assertIsNone(
            trv_write_gate(
                climate_state="heat",
                last_set=22.0,
                desired=30.0,
                now=5000.0,
                last_change=0.0,
                cooldown_sec=600.0,
                reported_setpoint=22.0,
                reported_eps=0.3,
                saturate_hi=30.0,
                saturate_margin=1.0,
                urgency="urgent",
                urgent_min_sec=180.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
