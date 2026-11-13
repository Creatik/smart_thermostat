"""Гвард «клапан без власти» (valve authority) для обучения offset.

Регресс по дампу 02.11: детская 18:39→19:31 — active_learning гнал offset
1.8→+6 (+0.3/тик) при мёртвой комнате 22.3 и local 23.4: клапан был
полностью открыт, но котёл/циркуляция тепла не давали. Симметрично —
эко-«перегрев» при закрытом клапане хоронил offset к −6 и убивал утро.

Запуск: python3 -m unittest tests.test_valve_authority -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import valve_learning_blocked, valve_ref_setpoint  # noqa: E402

TRAVEL = 2.0
HEAT = 1.5


class ValveAuthorityUpTests(unittest.TestCase):
    """Обучение ВВЕРХ (e > 0, недогрев)."""

    def test_blocked_when_valve_open_and_no_heat_flow(self):
        """Детская 02.11: set 26.3, local 23.4, room 22.5 → блок."""
        self.assertTrue(
            valve_learning_blocked(
                1, 26.3, 23.4, 22.5, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_allowed_when_heat_flowing(self):
        """Тепло течёт (local ≥ room+1.5) → учимся: offset держит клапан
        приоткрытым у цели (мягкая посадка), иначе клапан захлопнется."""
        self.assertFalse(
            valve_learning_blocked(
                1, 26.0, 25.0, 22.0, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_allowed_when_valve_not_fully_open(self):
        """set < local+margin → клапан ещё не на пределе, учиться можно."""
        self.assertFalse(
            valve_learning_blocked(
                1, 24.0, 23.4, 22.5, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_morning_recovery_from_minus6_not_blocked(self):
        """Утро: offset −6, set ≈ 19.5, local 19 (холодная батарея) →
        set < local+margin → быстрый выход из насыщения не страдает."""
        self.assertFalse(
            valve_learning_blocked(
                1, 19.5, 19.0, 19.0, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_blocked_without_room_temp(self):
        """room None → считаем «тепло не течёт», блок по положению клапана."""
        self.assertTrue(
            valve_learning_blocked(
                1, 26.3, 23.4, None, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )


class ValveAuthorityDownTests(unittest.TestCase):
    """Обучение ВНИЗ (e < 0, перегрев)."""

    def test_blocked_when_valve_closed(self):
        """Эко-вечер: set 16, local 24 (горячая батарея) → клапан уже закрыт,
        хоронить offset к −6 нельзя."""
        self.assertTrue(
            valve_learning_blocked(
                -1, 16.0, 24.0, 22.5, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_escape_from_plus6_not_blocked(self):
        """offset +6: set = 18+6−2.5 ≈ 21.5, local 22.5 → set > local−margin
        → быстрый выход из насыщения вниз работает."""
        self.assertFalse(
            valve_learning_blocked(
                -1, 21.5, 22.5, 22.5, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )

    def test_allowed_when_valve_has_reserve(self):
        """set выше local−margin → клапан ещё приоткрыт, учиться можно."""
        self.assertFalse(
            valve_learning_blocked(
                -1, 23.5, 24.0, 24.0, travel_margin=TRAVEL, heat_margin=HEAT
            )
        )


class ValveRefSetpointTests(unittest.TestCase):
    """Опорная уставка гварда: «худшая» для направления (батл 03.11, план п.1)."""

    def test_up_takes_max(self):
        """Вверх: last_set выше desired (PID прошлого тика) → берём его."""
        self.assertEqual(valve_ref_setpoint(1, 26.0, 24.0), 26.0)

    def test_up_takes_desired_when_last_set_lags_down(self):
        """Вверх: last_set занижен (mismatch/лаг Zigbee) → desired."""
        self.assertEqual(valve_ref_setpoint(1, 22.0, 24.0), 24.0)

    def test_down_takes_min(self):
        """Вниз: last_set выше desired → берём desired (худшая оценка)."""
        self.assertEqual(valve_ref_setpoint(-1, 26.0, 24.0), 24.0)

    def test_down_takes_last_set_when_lower(self):
        self.assertEqual(valve_ref_setpoint(-1, 20.0, 24.0), 20.0)

    def test_no_last_set_uses_desired(self):
        """Первые тики (last_set None) → desired."""
        self.assertEqual(valve_ref_setpoint(1, None, 24.0), 24.0)
        self.assertEqual(valve_ref_setpoint(-1, None, 24.0), 24.0)

    def test_garbage_falls_back_to_desired(self):
        self.assertEqual(
            valve_ref_setpoint(1, "abc", 24.0), 24.0  # type: ignore[arg-type]
        )

    def test_zero_direction_returns_desired(self):
        self.assertEqual(valve_ref_setpoint(0, 30.0, 24.0), 24.0)


class ValveAuthorityEdgeTests(unittest.TestCase):
    def test_no_local_sensor_no_guard(self):
        """local None (нет/битый сенсор) → гвард молчит в обе стороны."""
        self.assertFalse(valve_learning_blocked(1, 30.0, None, 22.0))
        self.assertFalse(valve_learning_blocked(-1, 15.0, None, 25.0))

    def test_zero_direction_no_guard(self):
        self.assertFalse(valve_learning_blocked(0, 30.0, 20.0, 22.0))

    def test_garbage_values_no_guard(self):
        self.assertFalse(
            valve_learning_blocked(1, "nan", "abc", 22.0)  # type: ignore[arg-type]
        )


if __name__ == "__main__":
    unittest.main()
