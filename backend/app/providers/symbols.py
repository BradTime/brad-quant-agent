"""Instrument code normalization across data sources.

Canonical form: ``<6 digits>.<EXCH>`` where EXCH in {SH, SZ, BJ}, e.g. ``600000.SH``.
Per-source conversions:
- BaoStock uses ``sh.600000`` / ``sz.000001``
- AkShare / efinance use the bare 6-digit code ``600000``
"""

from __future__ import annotations

import re

_PREFIX = {"SH": "sh", "SZ": "sz", "BJ": "bj"}
_CANONICAL = re.compile(r"^(?P<six>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$", re.I)
_SOURCE_PREFIX = re.compile(r"^(?P<exchange>SH|SZ|BJ)\.(?P<six>\d{6})$", re.I)


def infer_exchange(six: str) -> str:
    six = six.strip()
    if six.startswith(("60", "68", "90", "11", "51", "56", "58", "50")):
        return "SH"
    if six.startswith(("00", "30", "12", "15", "16", "18", "20", "39")):
        return "SZ"
    if six.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    return "SH" if six[:1] in "6789" else "SZ"


def to_canonical(six: str, exchange: str | None = None) -> str:
    six = six.strip()
    ex = (exchange or infer_exchange(six)).upper()
    return f"{six}.{ex}"


def normalize_a_share_code(code: str) -> str:
    """Return strict canonical A-share code, rejecting suffix conflicts."""
    raw = str(code).strip()
    match = _CANONICAL.fullmatch(raw) or _SOURCE_PREFIX.fullmatch(raw)
    if match is None:
        raise ValueError("股票代码必须是 6 位数字，可带 SH/SZ/BJ 后缀")
    six = match.group("six")
    explicit = match.group("exchange")
    inferred = infer_exchange(six)
    if explicit and explicit.upper() != inferred:
        raise ValueError("股票代码与交易所后缀不匹配")
    return f"{six}.{inferred}"


def normalize_a_share_codes(codes: list[str]) -> list[str]:
    normalized: list[str] = []
    for code in codes:
        value = normalize_a_share_code(code)
        if value not in normalized:
            normalized.append(value)
    return normalized


def split_canonical(code: str) -> tuple[str, str]:
    code = code.strip()
    if "." in code:
        six, ex = code.split(".", 1)
        return six, ex.upper()
    return code, infer_exchange(code)


def to_baostock(code: str) -> str:
    six, ex = split_canonical(code)
    return f"{_PREFIX.get(ex, 'sh')}.{six}"


def from_baostock(bcode: str) -> str:
    prefix, six = bcode.split(".", 1)
    return f"{six}.{prefix.upper()}"


def to_six(code: str) -> str:
    return split_canonical(code)[0]
