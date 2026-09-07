"""Redis-backed quote cache with local fallback."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core import redis_client
from app.providers.base import QuoteDTO
from app.services.quote_cache import QuoteCache


class FakeRedis:
    def __init__(self):
        self.values: dict[str, dict[bytes, bytes]] = {}
        self.fail = False

    def register_script(self, _script):
        def run(*, keys, args, client):
            assert client is self
            if self.fail:
                raise ConnectionError("redis down")
            key = keys[0]
            timestamp = int(args[0])
            current = int(self.values.get(key, {}).get(b"refreshed_at_ms", b"-1"))
            if current > timestamp:
                return 0
            self.values[key] = {
                b"schema": b"1",
                b"refreshed_at_ms": str(timestamp).encode(),
                b"payload": args[1],
            }
            return 1

        return run

    def hgetall(self, name: str):
        if self.fail:
            raise ConnectionError("redis down")
        return self.values.get(name, {})


@pytest.fixture
def shared_redis(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://test")
    monkeypatch.setattr(redis_client.settings, "redis_required", False)
    monkeypatch.setattr(redis_client, "_sync_client", fake)
    return fake


def _quote() -> QuoteDTO:
    return QuoteDTO(
        code="600000.SH",
        name="浦发银行",
        price=10.5,
        ts=datetime(2026, 8, 31, 7, 0, tzinfo=UTC),
    )


def test_quote_cache_is_shared_between_instances(shared_redis: FakeRedis):
    writer = QuoteCache()
    reader = QuoteCache()

    writer.set_stocks([_quote()], refreshed_at=123.0)

    rows, refreshed_at = reader.get_stocks_snapshot()
    assert [row.code for row in rows] == ["600000.SH"]
    assert refreshed_at == 123.0


def test_quote_cache_falls_back_to_local_snapshot_when_redis_fails(
    shared_redis: FakeRedis,
):
    cache = QuoteCache()
    cache.set_stocks([_quote()], refreshed_at=456.0)
    shared_redis.fail = True

    rows, refreshed_at = cache.get_stocks_snapshot()
    assert [row.code for row in rows] == ["600000.SH"]
    assert refreshed_at == 456.0


def test_older_shared_snapshot_cannot_replace_newer_one(shared_redis: FakeRedis):
    newer = QuoteCache()
    older = QuoteCache()
    reader = QuoteCache()

    newer.set_stocks([_quote()], refreshed_at=500.0)
    older.set_stocks([], refreshed_at=400.0)

    rows, refreshed_at = reader.get_stocks_snapshot()
    assert [row.code for row in rows] == ["600000.SH"]
    assert refreshed_at == 500.0


def test_required_shared_cache_fails_closed(
    shared_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
):
    cache = QuoteCache()
    cache.set_stocks([_quote()], refreshed_at=456.0)
    monkeypatch.setattr(redis_client.settings, "redis_required", True)
    monkeypatch.setattr(redis_client.settings, "redis_quote_l1_ttl_seconds", 0)
    shared_redis.fail = True

    with pytest.raises(redis_client.SharedStateUnavailable):
        cache.get_stocks_snapshot()
