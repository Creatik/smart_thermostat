"""Тесты мягкой посадки к указанной уставке.

Без Home Assistant: импорт чистых helpers/pid напрямую.
Запуск: python3 -m unittest tests.test_soft_landing -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "smart_thermostat"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from helpers import apply_soft_landing, soft_landing_factor  # noqa: E402
from pid import PIDController  # noqa: E402

# Согласовано с const.SOFT_LANDING_* / helpers defaults
DEADBAND = 0.5
FLOOR = 0.3
SPAN_MULT = 2.0
SPAN_MIN = 1.0
EASE_SPAN = max(SPAN_MIN, SPAN_MULT * DEADBAND)  # 1.0
BAND_HI = DEADBAND + EASE_SPAN  # 1.5


class SoftLandingFactorTests(unittest.TestCase):
    def test_far_from_target_full_power(self):
        """Далеко от уставки (e ≥ deadband+span) — PID не гасим."""
        self.assertEqual(soft_landing_factor(2.0, DEADBAND), 1.0)
        self.assertEqual(soft_landing_factor(BAND_HI, DEADBAND), 1.0)
        self.assertEqual(soft_landing_factor(5.0, DEADBAND), 1.0)

    def test_at_deadband_edge_floor(self):
        """У входа в мёртвую зону множитель = floor (не ноль — иначе рывок)."""
        f = soft_landing_factor(DEADBAND, DEADBAND)
        self.assertAlmostEqual(f, FLOOR, places=6)

    def test_just_above_deadband_near_floor(self):
        f = soft_landing_factor(DEADBAND + 0.05, DEADBAND)
        self.assertGreaterEqual(f, FLOOR)
        self.assertLess(f, 0.35)

    def test_mid_band_is_halfway(self):
        """Середина полосы посадки → множитель ~0.5 (выше пола)."""
        mid = DEADBAND + 0.5 * EASE_SPAN  # 1.0
        f = soft_landing_factor(mid, DEADBAND)
        self.assertAlmostEqual(f, 0.5, places=6)

    def test_monotonic_toward_setpoint(self):
        """При приближении к уставке (e↓) множитель не растёт."""
        errors = [2.0, 1.5, 1.2, 1.0, 0.8, 0.6, 0.51]
        factors = [soft_landing_factor(e, DEADBAND) for e in errors]
        for a, b in zip(factors, factors[1:]):
            self.assertGreaterEqual(a, b - 1e-12)

    def test_overshoot_side_not_damped(self):
        """Перегрев (error ≤ 0) — посадку не применяем."""
        self.assertEqual(soft_landing_factor(0.0, DEADBAND), 1.0)
        self.assertEqual(soft_landing_factor(-0.8, DEADBAND), 1.0)

    def test_apply_scales_correction(self):
        raw = 1.0
        eased = apply_soft_landing(raw, DEADBAND + 0.25, DEADBAND)
        self.assertAlmostEqual(eased, raw * soft_landing_factor(DEADBAND + 0.25, DEADBAND))

    def test_custom_deadband_span(self):
        """deadband=1.0 → span=max(1, 2)=2 → полоса до 3.0."""
        db = 1.0
        self.assertEqual(soft_landing_factor(3.0, db), 1.0)
        self.assertAlmostEqual(soft_landing_factor(2.0, db), 0.5, places=6)
        self.assertAlmostEqual(soft_landing_factor(1.0, db), FLOOR, places=6)


class SoftLandingApproachTests(unittest.TestCase):
    """Интегральный сценарий: уставка TRV мягче садится к baseline у цели."""

    def _trv(self, t_target: float, offset: float, correction: float, e: float) -> float:
        return t_target + offset + apply_soft_landing(correction, e, DEADBAND)

    def test_trv_closer_to_baseline_near_target(self):
        """При той же сырой коррекции ближе к цели TRV ниже (мягче)."""
        t_target = 23.0
        offset = 0.0
        raw_correction = 1.0
        far = self._trv(t_target, offset, raw_correction, e=2.5)
        near = self._trv(t_target, offset, raw_correction, e=0.6)
        baseline = t_target + offset
        self.assertGreater(far, near)
        self.assertGreater(near, baseline)
        # У края deadband добавка ≤ floor × raw
        edge = self._trv(t_target, offset, raw_correction, e=DEADBAND + 1e-6)
        self.assertLessEqual(edge - baseline, FLOOR * raw_correction + 1e-9)

    def test_pid_approach_damps_before_deadband(self):
        """Симуляция нагрева к 23°C: у deadband+ε демпфированный PID < сырого."""
        target = 23.0
        pid_raw = PIDController(kp=0.6, ki=0.0, kd=0.0)
        pid_soft = PIDController(kp=0.6, ki=0.0, kd=0.0)
        now = 0.0
        rooms = [20.0, 21.0, 21.5, 22.0, 22.3, 22.45]
        soft_corrections = []
        raw_corrections = []
        for room in rooms:
            now += 240.0
            e = target - room
            raw = pid_raw.update(e, target, now, step_max=1.0)
            soft = apply_soft_landing(
                pid_soft.update(e, target, now, step_max=1.0), e, DEADBAND
            )
            raw_corrections.append(raw)
            soft_corrections.append(soft)

        # Далеко (e=3) — одинаково
        self.assertAlmostEqual(soft_corrections[0], raw_corrections[0], places=6)
        # Уже в полосе посадки (e=0.55 при room=22.45) — мягче
        self.assertLess(soft_corrections[-1], raw_corrections[-1])
        self.assertGreater(soft_corrections[-1], 0.0)
        # Множители убывают по мере приближения
        factors = [
            soft_landing_factor(target - r, DEADBAND) for r in rooms
        ]
        for a, b in zip(factors, factors[1:]):
            self.assertGreaterEqual(a, b - 1e-12)

    def test_no_slam_into_deadband_with_full_step(self):
        """Регресс P0-1: у e=deadband+ε коррекция не равна полной step_max."""
        step_max = 1.0
        e = DEADBAND + 0.05  # active_control ещё вызывается
        slammed = step_max  # старое поведение без посадки
        landed = apply_soft_landing(slammed, e, DEADBAND)
        self.assertLess(landed, 0.5 * slammed)
        self.assertGreaterEqual(landed, FLOOR * slammed - 1e-9)


if __name__ == "__main__":
    unittest.main()
