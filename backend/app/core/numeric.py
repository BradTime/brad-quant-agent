"""Safe numeric parsing helpers (defensive against ''/'-'/NaN from data sources)."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

_NULL_STRINGS = {"", "-", "--", "none", "null", "nan", "无"}


def to_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
            return None
        f = float(value)  # type: ignore[arg-type]
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def to_decimal(value: object, places: int = 4) -> Decimal | None:
    f = to_float(value)
    if f is None:
        return None
    try:
        return Decimal(str(round(f, places)))
    except (InvalidOperation, ValueError):
        return None


def to_int(value: object) -> int | None:
    f = to_float(value)
    if f is None:
        return None
    return int(round(f))
