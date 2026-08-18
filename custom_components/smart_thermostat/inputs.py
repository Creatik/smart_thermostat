"""Входные данные для контроллера."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Inputs:
    """Снимок состояния на момент тика контроллера."""

    climate_entity: str
    climate_state: Any
    t_room: float
    t_target: float      # базовая цель (для обучения)
    t_effective: float   # цель + эко/погода (для управления)
    hvac_mode: str
    window_open: bool
    now_mono: float