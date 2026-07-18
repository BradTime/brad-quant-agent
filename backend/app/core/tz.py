"""A-share market timezone helpers (Asia/Shanghai)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Shanghai")


def market_today() -> date:
    """Return the current A-share calendar date in Shanghai."""
    return datetime.now(MARKET_TZ).date()


def market_now() -> datetime:
    """Return the current wall-clock time in Shanghai."""
    return datetime.now(MARKET_TZ)
