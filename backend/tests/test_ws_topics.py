"""WS topic 规范化、配额与连接订阅上限。"""

from __future__ import annotations

import asyncio

from app.ws import topics as topic_rules
from app.ws.manager import ConnectionManager


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        return None

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)


def test_normalize_topic_accepts_indices_and_canonical_quote():
    assert topic_rules.normalize_topic("market.indices") == "market.indices"
    assert topic_rules.normalize_topic("market.quote.600000.SH") == "market.quote.600000.SH"
    assert topic_rules.normalize_topic("market.quote.600000") == "market.quote.600000.SH"


def test_normalize_topic_rejects_unknown():
    assert topic_rules.normalize_topic("market.private") is None
    assert topic_rules.normalize_topic("market.quote.") is None
    assert topic_rules.normalize_topic("not-a-topic") is None


def test_filter_topics_dedupes_and_caps_batch():
    accepted, rejected = topic_rules.filter_topics(
        [
            "market.indices",
            "market.indices",
            "market.quote.600000.SH",
            "bad.topic",
            "market.quote.000001.SZ",
        ]
    )
    assert accepted == [
        "market.indices",
        "market.quote.600000.SH",
        "market.quote.000001.SZ",
    ]
    assert "bad.topic" in rejected


def test_subscribe_rate_limit_sliding_window():
    cid = 4242
    topic_rules.clear_subscribe_bucket(cid)
    for _ in range(topic_rules.SUBSCRIBE_RATE_LIMIT):
        assert topic_rules.allow_subscribe(cid) is True
    assert topic_rules.allow_subscribe(cid) is False
    topic_rules.clear_subscribe_bucket(cid)


def test_manager_subscribe_enforces_max_topics():
    async def run():
        mgr = ConnectionManager()
        ws = FakeWS()
        await mgr.connect(ws)
        # filter_topics 单批上限 MAX_SUBSCRIBE_BATCH，分两批填满连接配额
        first = [f"market.quote.{i:06d}.SH" for i in range(topic_rules.MAX_SUBSCRIBE_BATCH)]
        current, rejected = await mgr.subscribe(ws, first)
        assert len(current) == topic_rules.MAX_SUBSCRIBE_BATCH
        assert rejected == []
        room = topic_rules.MAX_TOPICS_PER_CONNECTION - topic_rules.MAX_SUBSCRIBE_BATCH
        second = [
            f"market.quote.{i:06d}.SZ"
            for i in range(room + 2)
        ]
        current, rejected2 = await mgr.subscribe(ws, second)
        assert len(current) == topic_rules.MAX_TOPICS_PER_CONNECTION
        assert len(rejected2) == 2

    asyncio.run(run())


def test_send_json_timeout_returns_false():
    class SlowWS(FakeWS):
        async def send_json(self, msg: dict) -> None:
            await asyncio.sleep(5)
            self.sent.append(msg)

    async def run():
        mgr = ConnectionManager()
        ws = SlowWS()
        await mgr.connect(ws)
        ok = await mgr.send_json(ws, {"type": "ping"})
        assert ok is False

    asyncio.run(run())
