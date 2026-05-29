"""Date/time parsing helpers shared by data providers."""

from __future__ import annotations

from datetime import date, datetime


def parse_date(value: object) -> date | None:
    """Parse 'YYYY-MM-DD' / 'YYYYMMDD' / date / datetime into a ``date``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: object) -> datetime | None:
    """Parse a daily date into a midnight ``datetime`` (or pass through datetime)."""
    if isinstance(value, datetime):
        return value
    d = parse_date(value)
    return datetime(d.year, d.month, d.day) if d else None


def parse_baostock_time(value: object) -> datetime | None:
    """BaoStock minute ``time`` field looks like ``20170703093500000``."""
    s = str(value or "").strip()
    if len(s) < 14:
        return None
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
