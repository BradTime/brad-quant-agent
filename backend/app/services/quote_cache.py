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

    def set_stocks(self, quotes: list[QuoteDTO]) -> None:
        with self._lock:
            self._stocks = list(quotes)
            self._stocks_ts = time.time()

    def get_stocks(self) -> list[QuoteDTO]:
        with self._lock:
            return list(self._stocks)

    def set_indices(self, quotes: list[QuoteDTO]) -> None:
        with self._lock:
            self._indices = list(quotes)
            self._indices_ts = time.time()

    def get_indices(self) -> list[QuoteDTO]:
        with self._lock:
            return list(self._indices)

    def status(self) -> dict:
        with self._lock:
            return {
                "stocks": len(self._stocks),
                "stocks_ts": self._stocks_ts,
                "indices": len(self._indices),
                "indices_ts": self._indices_ts,
            }


cache = QuoteCache()
