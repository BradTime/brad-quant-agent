"""WebSocket connection manager: tracks clients, topic subscriptions, and the
authenticated user behind each socket (for **private per-user push**, e.g.
Phase 3 成交回报 / 持仓变动 / 通知——区别于行情广播)。"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._subs: dict[WebSocket, set[str]] = {}
        self._users: dict[WebSocket, str] = {}
        self._by_user: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        # 捕获应用事件循环引用，供同步调用方（撮合/调度器）线程安全地下发私有事件
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        async with self._lock:
            self._subs[ws] = set()

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.pop(ws, None)
            uid = self._users.pop(ws, None)
            if uid and uid in self._by_user:
                self._by_user[uid].discard(ws)
                if not self._by_user[uid]:
                    self._by_user.pop(uid, None)

    async def bind_user(self, ws: WebSocket, user_id: str | None) -> None:
        """把已鉴权 socket 关联到 user_id，建立私有推送的反向索引。"""
        if not user_id:
            return
        async with self._lock:
            self._users[ws] = user_id
            self._by_user.setdefault(user_id, set()).add(ws)

    async def send_to_user(self, user_id: str, message: dict) -> int:
        """把消息只发给该 user 的所有在线连接；返回成功下发的连接数。"""
        async with self._lock:
            targets = list(self._by_user.get(user_id, ()))
        sent = 0
        for ws in targets:
            try:
                await ws.send_json(message)
                sent += 1
            except Exception:  # noqa: BLE001  (client gone; cleaned up on disconnect)
                pass
        return sent

    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    async def subscribe(self, ws: WebSocket, topics: list[str]) -> set[str]:
        async with self._lock:
            if ws in self._subs:
                self._subs[ws].update(t for t in topics if isinstance(t, str))
                return set(self._subs[ws])
        return set()

    async def unsubscribe(self, ws: WebSocket, topics: list[str]) -> set[str]:
        async with self._lock:
            if ws in self._subs:
                self._subs[ws].difference_update(topics)
                return set(self._subs[ws])
        return set()

    async def snapshot(self) -> list[tuple[WebSocket, set[str]]]:
        async with self._lock:
            return [(ws, set(topics)) for ws, topics in self._subs.items()]

    async def count(self) -> int:
        async with self._lock:
            return len(self._subs)


manager = ConnectionManager()
