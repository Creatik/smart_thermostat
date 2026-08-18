"""Чистые вспомогательные функции (без зависимостей от Home Assistant)."""
from __future__ import annotations

import re
from typing import Any, Optional

_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def clamp(v: float, lo: float, hi: float) -> float:
    """Ограничить значение диапазоном [lo, hi]."""
    return max(lo, min(hi, v))


def round_step(v: float, step: float) -> float:
    """Округлить до ближайшего кратного step."""
    if step <= 0:
        return v
    return round(v / step) * step


def to_float(value: Any) -> Optional[float]:
    """Преобразовать значение (state/attr) в float.

    Возвращает None для unknown/unavailable/пустых/непарсящихся значений.
    Принимает строки вида: "22.5", "22,5", "22.5 °C", "temp: 22,5" и т.п.
    """
    if value is None:
        return None

    # Быстрый путь для чисел
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        # Отсекаем NaN/inf
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f

    s = str(value).strip().lower()
    if s in ("unavailable", "unknown", "none", "", "uninitialized", "nan", "null"):
        return None

    m = _NUM_RE.search(s)
    if not m:
        return None

    num = m.group(0).replace(",", ".")
    try:
        f = float(num)
    except (TypeError, ValueError):
        return None

    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def normalize_entity_list(value: Any) -> list[str]:
    """Нормализовать значение селектора/конфига в список entity_id."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            if v is None:
                continue
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and "entity_id" in v:
                out.append(v["entity_id"])
        return [x for x in out if x]
    return []


def is_truthy_state(state: Any) -> bool:
    """Считать состояние истинным (on/open/true/1)."""
    if state is None:
        return False
    return str(state).lower() in ("on", "open", "true", "1")