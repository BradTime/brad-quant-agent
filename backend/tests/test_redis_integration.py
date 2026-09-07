"""Real-Redis coordination contracts (enabled only when REDIS_URL is set)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core import redis_client
from app.providers.base import QuoteDTO
from app.services import rate_limit
from app.services.quote_cache import QuoteCache
from app.services.scheduler_leader import RedisLease

pytestmark = pytest.mark.skipif(
    not os.environ.get("REDIS_URL"), reason="requires a real Redis service"
)


def test_real_redis_atomic_gates_and_stale_write_rejection():
    client = redis_client.get_redis()
    assert client is not None and client.ping()
    user_id = f"integration-{uuid4().hex}"

    with ThreadPoolExecutor(max_workers=20) as pool:
        admitted = list(
            pool.map(
                lambda _: rate_limit.ai_cost_gate(
                    user_id, "chat", quota=7, interval=0
                ),
                range(20),
            )
        )
    assert sum(result is None for result in admitted) == 7

    with ThreadPoolExecutor(max_workers=20) as pool:
        refresh = list(
            pool.map(
                lambda _: rate_limit.acquire_refresh_cooldown(
                    user_id, "600000.SH"
                ),
                range(20),
            )
        )
    assert sum(result is None for result in refresh) == 1

    cache = QuoteCache()
    key = cache._redis_key("stocks")
    client.delete(key)
    try:
        now = time.time()
        quote = QuoteDTO(
            code="600000.SH",
            name="浦发银行",
            price=10.5,
            ts=datetime.now(UTC),
        )
        QuoteCache().set_stocks([quote], refreshed_at=now + 2)
        QuoteCache().set_stocks([], refreshed_at=now + 1)
        rows, refreshed_at = QuoteCache().get_stocks_snapshot()
        assert [row.code for row in rows] == ["600000.SH"]
        assert refreshed_at == int((now + 2) * 1000) / 1000
    finally:
        client.delete(key)


def test_real_redis_lease_takeover_and_pubsub_fanout():
    client = redis_client.get_redis()
    assert client is not None
    lease_key = redis_client.key("test", "lease", uuid4().hex)
    first = RedisLease(client, lease_key, ttl_seconds=10, token="first")
    second = RedisLease(client, lease_key, ttl_seconds=10, token="second")
    try:
        assert first.try_acquire()
        assert not second.try_acquire()
        assert first.renew()
        assert first.release()
        assert second.try_acquire()
    finally:
        second.release()
        client.delete(lease_key)

    async def verify_fanout() -> None:
        async_client = redis_client.get_async_redis()
        assert async_client is not None
        channel = redis_client.key("test", "pubsub", uuid4().hex)
        subscribers = [async_client.pubsub(), async_client.pubsub()]
        try:
            for subscriber in subscribers:
                await subscriber.subscribe(channel)
                await subscriber.get_message(
                    ignore_subscribe_messages=False, timeout=1
                )
            payload = json.dumps({"event": "integration"})
            assert await async_client.publish(channel, payload) == 2
            for subscriber in subscribers:
                message = None
                for _ in range(20):
                    message = await subscriber.get_message(
                        ignore_subscribe_messages=True, timeout=0.1
                    )
                    if message is not None:
                        break
                assert message is not None
                assert json.loads(message["data"]) == {"event": "integration"}
        finally:
            for subscriber in subscribers:
                await subscriber.aclose()

    asyncio.run(verify_fanout())
