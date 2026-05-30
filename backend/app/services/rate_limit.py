"""Simple in-process rate limit for expensive market refresh (per user + code)."""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_LAST_REFRESH: dict[tuple[str, str], float] = {}

REFRESH_COOLDOWN_SEC = 60


def seconds_until_refresh_allowed(user_id: str, code: str) -> float | None:
    """Return seconds to wait if throttled, else None."""
    key = (user_id, code)
    now = time.time()
    with _LOCK:
        last = _LAST_REFRESH.get(key, 0.0)
        elapsed = now - last
        if elapsed < REFRESH_COOLDOWN_SEC:
            return REFRESH_COOLDOWN_SEC - elapsed
    return None


def mark_refresh(user_id: str, code: str) -> None:
    key = (user_id, code)
    with _LOCK:
        _LAST_REFRESH[key] = time.time()
