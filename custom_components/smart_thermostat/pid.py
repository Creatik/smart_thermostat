"""PID-контроллер для коррекции уставки термостата."""
from __future__ import annotations

from typing import Optional


class PIDController:
    """Позиционный PID с анти-виндиапом и сбросом при смене цели.

    Выход ограничен [-step_max, step_max]. Интегральный член накапливается
    только пока P-член не насыщен (анти-виндиап), что предотвращает
    перекручивание интеграла при достижении предела уставки.
    """

    def __init__(self, kp: float = 0.6, ki: float = 0.05, kd: float = 0.1):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.i = 0.0
        self.prev_e: Optional[float] = None
        self.prev_time: Optional[float] = None
        self.prev_target: Optional[float] = None

    def reset(self) -> None:
        """Сбросить интеграл, производную и эталон цели."""
        self.i = 0.0
        self.prev_e = None
        self.prev_time = None
        self.prev_target = None

    def update(self, e: float, target: float, now_mono: float,
               step_max: float, i_limit: float = 20.0) -> float:
        """Вычислить корректирующую уставку по ошибке e = target - t_room."""
        if self.prev_target is None or abs(target - self.prev_target) > 0.01:
            # Смена цели или первый вызов — сброс
            self.i = 0.0
            self.prev_e = e
            self.prev_target = target
            self.prev_time = now_mono
            return self._clamp(self.kp * e, step_max)

        dt = now_mono - self.prev_time
        if dt < 0.1 or dt > 600:
            # Некорректный интервал — пропускаем накопление
            self.prev_e = e
            self.prev_time = now_mono
            return self._clamp(self.kp * e, step_max)

        # Анти-виндиап: интегрируем только пока P-член не насыщен
        if abs(self.kp * e) < step_max:
            self.i += self.ki * e * dt
            self.i = self._clamp(self.i, i_limit)

        deriv = (e - self.prev_e) / dt if dt > 0 else 0.0
        out = self.kp * e + self.i + self.kd * deriv

        self.prev_e = e
        self.prev_time = now_mono
        return self._clamp(out, step_max)

    @staticmethod
    def _clamp(v: float, limit: float) -> float:
        return max(-limit, min(limit, v))