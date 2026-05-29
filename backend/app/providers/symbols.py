"""Instrument code normalization across data sources.

Canonical form: ``<6 digits>.<EXCH>`` where EXCH in {SH, SZ, BJ}, e.g. ``600000.SH``.
Per-source conversions:
- BaoStock uses ``sh.600000`` / ``sz.000001``
- AkShare / efinance use the bare 6-digit code ``600000``
"""

from __future__ import annotations

_PREFIX = {"SH": "sh", "SZ": "sz", "BJ": "bj"}


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
