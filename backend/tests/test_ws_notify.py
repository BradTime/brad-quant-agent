"""WS 私有定向推送：验证 send_to_user 只路由到对应 user 的连接、断开后清理。"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core import redis_client
from app.ws.manager import ConnectionManager
from app.ws.notify import _envelope


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:  # noqa: D401
        return None

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)


def test_send_to_user_routes_only_to_that_user():
    async def run():
        mgr = ConnectionManager()
        a1, a2, b1 = FakeWS(), FakeWS(), FakeWS()
        for ws in (a1, a2, b1):
            await mgr.connect(ws)
        await mgr.bind_user(a1, "userA")
        await mgr.bind_user(a2, "userA")
        await mgr.bind_user(b1, "userB")

        sent = await mgr.send_to_user("userA", {"type": "trade.fill", "payload": {"x": 1}})
        assert sent == 2
        assert len(a1.sent) == 1 and len(a2.sent) == 1
        assert b1.sent == []  # 别的用户收不到

        # 未知用户：0 送达
        assert await mgr.send_to_user("ghost", {"type": "x"}) == 0

        # 断开一个连接后只剩一个目标
        await mgr.disconnect(a1)
        assert await mgr.send_to_user("userA", {"type": "notify"}) == 1

    asyncio.run(run())


def test_envelope_shape():
    env = _envelope("trade.fill", {"orderId": "o1"})
    assert env["type"] == "trade.fill"
    assert env["payload"] == {"orderId": "o1"}
    assert isinstance(env["timestamp"], int)


def test_threadsafe_notify_closes_coroutine_when_scheduling_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.ws import notify

    async def pending_send():
        return 0

    coroutine = pending_send()
    monkeypatch.setattr(notify.manager, "loop", lambda: object())
    monkeypatch.setattr(notify.manager, "send_to_user", lambda *_args: coroutine)

    def fail_schedule(_coroutine, _loop):
        raise RuntimeError("loop closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fail_schedule)

    assert notify.notify_user_threadsafe("userA", "trade.fill", {}) is False
    assert coroutine.cr_frame is None


def test_threadsafe_notify_publishes_to_redis_without_local_event_loop(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.ws import notify

    published: list[tuple[str, bytes]] = []
    fake = type(
        "FakeRedis",
        (),
        {"publish": lambda _self, channel, payload: published.append((channel, payload)) or 1},
    )()
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://test")
    monkeypatch.setattr(redis_client, "_sync_client", fake)
    monkeypatch.setattr(notify.manager, "loop", lambda: None)

    assert notify.notify_user_threadsafe("userA", "trade.fill", {"id": "o1"}) is True
    channel, raw = published[0]
    assert channel == redis_client.key("ws", "private")
    message = json.loads(raw)
    assert message["userId"] == "userA"
    assert message["event"]["type"] == "trade.fill"


def test_redis_bridge_delivers_event_to_api_local_connections(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.ws import redis_bridge

    sent: list[tuple[str, dict]] = []

    class FakePubSub:
        async def subscribe(self, _channel):
            return None

        async def listen(self):
            yield {"type": "subscribe", "data": 1}
            yield {
                "type": "message",
                "data": json.dumps(
                    {
                        "v": 1,
                        "eventId": "event-1",
                        "userId": "userA",
                        "event": {
                            "type": "trade.fill",
                            "payload": {"id": "o1"},
                            "timestamp": 123,
                        },
                    }
                ).encode(),
            }
            raise asyncio.CancelledError

        async def aclose(self):
            return None

    fake_client = type("FakeAsyncRedis", (), {"pubsub": lambda _self: FakePubSub()})()
    monkeypatch.setattr(redis_client, "get_async_redis", lambda: fake_client)

    async def fake_send(user_id: str, event: dict):
        sent.append((user_id, event))
        return 1

    monkeypatch.setattr(redis_bridge.manager, "send_to_user", fake_send)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(redis_bridge.listen_private_events())
    assert sent == [
        (
            "userA",
            {"type": "trade.fill", "payload": {"id": "o1"}, "timestamp": 123},
        )
    ]
