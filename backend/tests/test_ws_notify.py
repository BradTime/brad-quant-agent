"""WS 私有定向推送：验证 send_to_user 只路由到对应 user 的连接、断开后清理。"""

from __future__ import annotations

import asyncio

import pytest

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

    coroutine = notify.notify_user("userA", "trade.fill", {"orderId": "o1"})
    monkeypatch.setattr(notify.manager, "loop", lambda: object())
    monkeypatch.setattr(notify, "notify_user", lambda *_args: coroutine)

    def fail_schedule(_coroutine, _loop):
        raise RuntimeError("loop closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fail_schedule)

    assert notify.notify_user_threadsafe("userA", "trade.fill", {}) is False
    assert coroutine.cr_frame is None
