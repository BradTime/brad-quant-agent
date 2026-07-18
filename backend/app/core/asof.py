"""Shared parsing for point-in-time query cutoffs."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_as_of(value: str | None) -> datetime | None:
    """Parse RFC3339 or a Shanghai calendar date into an absolute UTC instant."""
    if value is None:
        return None
    if len(value) == 10:
        local_date = date.fromisoformat(value)
        parsed = datetime.combine(local_date, time.max, tzinfo=_SHANGHAI)
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(UTC)
