"""In-memory cache of the latest realtime snapshots.

The scheduler refreshes this from the data source so HTTP requests are served
from memory (and we hit the free source once centrally rather than per request).
This is the precursor to the WebSocket broadcast layer.
"""

from __future__ import annotations

import threading
import time

from app.providers.base import QuoteDTO


class QuoteCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stocks: list[QuoteDTO] = []
        self._indices: list[QuoteDTO] = []
        self._stocks_ts = 0.0
        self._indices_ts = 0.0

    def set_stocks(
        self, quotes: list[QuoteDTO], *, refreshed_at: float | None = None
    ) -> None:
        with self._lock:
            self._stocks = list(quotes)
            self._stocks_ts = time.time() if refreshed_at is None else refreshed_at

    def get_stocks(self) -> list[QuoteDTO]:
        with self._lock:
            return list(self._stocks)

    def get_stocks_snapshot(self) -> tuple[list[QuoteDTO], float]:
        """Atomically return quotes and the cache refresh wall-clock timestamp."""
        with self._lock:
            return list(self._stocks), self._stocks_ts

    def set_indices(
        self, quotes: list[QuoteDTO], *, refreshed_at: float | None = None
    ) -> None:
        with self._lock:
            self._indices = list(quotes)
            self._indices_ts = time.time() if refreshed_at is None else refreshed_at

    def get_indices(self) -> list[QuoteDTO]:
        with self._lock:
            return list(self._indices)

    def get_indices_snapshot(self) -> tuple[list[QuoteDTO], float]:
        """Atomically return index quotes and their cache refresh timestamp."""
        with self._lock:
            return list(self._indices), self._indices_ts

    def status(self) -> dict:
        with self._lock:
            return {
                "stocks": len(self._stocks),
                "stocks_ts": self._stocks_ts,
                "indices": len(self._indices),
                "indices_ts": self._indices_ts,
            }


cache = QuoteCache()
