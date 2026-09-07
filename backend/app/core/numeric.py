"""Safe numeric parsing helpers (defensive against ''/'-'/NaN from data sources)."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

_NULL_STRINGS = {"", "-", "--", "none", "null", "nan", "无", "false"}

# 中文数量级后缀（按长度降序，避免"万亿"被"亿"截断）。
_CN_UNITS: list[tuple[str, float]] = [
    ("万亿", 1e12),
    ("亿", 1e8),
    ("万", 1e4),
    ("千", 1e3),
]


def to_float(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            # 注意：bool 也要排除，否则 float(False)==0.0 会把"缺失"误当成 0。
            return None
        if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
            return None
        f = float(value)  # type: ignore[arg-type]
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def parse_cn_number(value: object) -> float | None:
    """解析带中文单位/百分号的财经数值字符串。

    例：``"1.47亿"`` -> ``147000000.0``，``"54.27%"`` -> ``54.27``，
    缺失标记 ``False`` / ``"--"`` -> ``None``。百分号仅剥离、不做 /100。
    """
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, str):
        return to_float(value)
    s = value.strip().replace(",", "")
    if s.lower() in _NULL_STRINGS:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    mult = 1.0
    for suffix, m in _CN_UNITS:
        if s.endswith(suffix):
            mult = m
            s = s[: -len(suffix)].strip()
            break
    f = to_float(s)
    return None if f is None else f * mult


def parse_cn_decimal(value: object) -> Decimal | None:
    """Parse a financial source value without converting through binary float."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    text = str(value).strip().replace(",", "")
    if text.lower() in _NULL_STRINGS:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    multiplier = Decimal(1)
    for suffix, numeric_multiplier in _CN_UNITS:
        if text.endswith(suffix):
            multiplier = Decimal(str(numeric_multiplier))
            text = text[: -len(suffix)].strip()
            break
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed * multiplier


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
