"""Realtime quote cache with optional Redis sharing and local fallback.

The scheduler refreshes this from the data source so HTTP requests are served
from cache (and we hit the free source once centrally rather than per request).
Redis lets scheduler and API processes share snapshots; local memory preserves
single-process development and provides a last-known fallback during outages.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import zlib

from app.core import redis_client
from app.core.config import settings
from app.providers.base import QuoteDTO

logger = logging.getLogger(__name__)

_WRITE_SNAPSHOT_SCRIPT = """
local current = tonumber(redis.call('HGET', KEYS[1], 'refreshed_at_ms') or '-1')
local incoming = tonumber(ARGV[1])
if current > incoming then
  return 0
end
redis.call('HSET', KEYS[1],
  'schema', '1',
  'refreshed_at_ms', ARGV[1],
  'payload', ARGV[2])
redis.call('PEXPIRE', KEYS[1], ARGV[3])
return 1
"""


class QuoteCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stocks: list[QuoteDTO] = []
        self._indices: list[QuoteDTO] = []
        self._stocks_ts = 0.0
        self._indices_ts = 0.0
        self._stocks_read_at = 0.0
        self._indices_read_at = 0.0

    @staticmethod
    def _redis_key(kind: str) -> str:
        return redis_client.key("quotes", kind)

    def _set_shared(
        self,
        kind: str,
        quotes: list[QuoteDTO],
        refreshed_at: float,
    ) -> None:
        client = redis_client.get_redis()
        if client is None:
            return
        payload = zlib.compress(
            json.dumps(
                [quote.model_dump(mode="json") for quote in quotes],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        refreshed_at_ms = int(refreshed_at * 1000)
        ttl_ms = max(int(settings.redis_quote_ttl_seconds), 60) * 1000
        try:
            if hasattr(client, "hgetall"):
                script = client.register_script(_WRITE_SNAPSHOT_SCRIPT)
                script(
                    keys=[self._redis_key(kind)],
                    args=[refreshed_at_ms, payload, ttl_ms],
                    client=client,
                )
                return
            # Minimal test doubles and old local adapters use the legacy value
            # shape. Real Redis always takes the atomic hash/Lua path above.
            legacy_payload = json.dumps(
                {
                    "quotes": [quote.model_dump(mode="json") for quote in quotes],
                    "refreshedAt": refreshed_at,
                },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
            client.set(
                self._redis_key(kind),
                legacy_payload,
                ex=max(int(settings.redis_quote_ttl_seconds), 60),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis quote cache write failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("quote_cache_write", exc) from exc

    def _get_shared(self, kind: str) -> tuple[list[QuoteDTO], float] | None:
        client = redis_client.get_redis()
        if client is None:
            return None
        try:
            if hasattr(client, "hgetall"):
                fields = client.hgetall(self._redis_key(kind))
                if not fields:
                    return None
                raw_payload = fields.get(b"payload") or fields.get("payload")
                raw_ts = fields.get(b"refreshed_at_ms") or fields.get(
                    "refreshed_at_ms"
                )
                if raw_payload is None or raw_ts is None:
                    raise ValueError("incomplete quote snapshot")
                items = json.loads(zlib.decompress(raw_payload))
                quotes = [QuoteDTO.model_validate(item) for item in items]
                return quotes, int(raw_ts) / 1000
            raw = client.get(self._redis_key(kind))
            if not raw:
                return None
            legacy = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            quotes = [QuoteDTO.model_validate(item) for item in legacy.get("quotes", [])]
            return quotes, float(legacy.get("refreshedAt") or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis quote cache read failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("quote_cache_read", exc) from exc
            return None

    def _local_snapshot(self, kind: str) -> tuple[list[QuoteDTO], float]:
        with self._lock:
            if kind == "stocks":
                return list(self._stocks), self._stocks_ts
            return list(self._indices), self._indices_ts

    def _snapshot(self, kind: str) -> tuple[list[QuoteDTO], float]:
        if not redis_client.enabled():
            return self._local_snapshot(kind)
        now = time.monotonic()
        with self._lock:
            read_at = self._stocks_read_at if kind == "stocks" else self._indices_read_at
        if now - read_at <= max(settings.redis_quote_l1_ttl_seconds, 0):
            return self._local_snapshot(kind)
        shared = self._get_shared(kind)
        if shared is None:
            if redis_client.required():
                return [], 0.0
            return self._local_snapshot(kind)
        quotes, refreshed_at = shared
        with self._lock:
            if kind == "stocks":
                self._stocks = list(quotes)
                self._stocks_ts = refreshed_at
                self._stocks_read_at = now
            else:
                self._indices = list(quotes)
                self._indices_ts = refreshed_at
                self._indices_read_at = now
        return list(quotes), refreshed_at

    def set_stocks(
        self, quotes: list[QuoteDTO], *, refreshed_at: float | None = None
    ) -> None:
        timestamp = time.time() if refreshed_at is None else refreshed_at
        with self._lock:
            if timestamp >= self._stocks_ts:
                self._stocks = list(quotes)
                self._stocks_ts = timestamp
                self._stocks_read_at = time.monotonic()
        self._set_shared("stocks", quotes, timestamp)

    def get_stocks(self) -> list[QuoteDTO]:
        return self.get_stocks_snapshot()[0]

    def get_stocks_snapshot(self) -> tuple[list[QuoteDTO], float]:
        """Atomically return quotes and the cache refresh wall-clock timestamp."""
        return self._snapshot("stocks")

    def set_indices(
        self, quotes: list[QuoteDTO], *, refreshed_at: float | None = None
    ) -> None:
        timestamp = time.time() if refreshed_at is None else refreshed_at
        with self._lock:
            if timestamp >= self._indices_ts:
                self._indices = list(quotes)
                self._indices_ts = timestamp
                self._indices_read_at = time.monotonic()
        self._set_shared("indices", quotes, timestamp)

    def get_indices(self) -> list[QuoteDTO]:
        return self.get_indices_snapshot()[0]

    def get_indices_snapshot(self) -> tuple[list[QuoteDTO], float]:
        """Atomically return index quotes and their cache refresh timestamp."""
        return self._snapshot("indices")

    def status(self) -> dict:
        stocks, stocks_ts = self.get_stocks_snapshot()
        indices, indices_ts = self.get_indices_snapshot()
        return {
            "stocks": len(stocks),
            "stocks_ts": stocks_ts,
            "indices": len(indices),
            "indices_ts": indices_ts,
            "shared": redis_client.enabled(),
        }


cache = QuoteCache()
