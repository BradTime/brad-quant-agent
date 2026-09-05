"""WebSocket connection manager: tracks clients, topic subscriptions, and the
authenticated user behind each socket (for **private per-user push**, e.g.
Phase 3 成交回报 / 持仓变动 / 通知——区别于行情广播)。"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from app.ws import topics as topic_rules

# 单次 send 超时，避免慢客户端拖死广播循环
SEND_TIMEOUT_SECONDS = 2.0


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
        topic_rules.clear_subscribe_bucket(id(ws))
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

    async def send_json(self, ws: WebSocket, message: dict) -> bool:
        """带超时发送；成功 True，超时/断开 False。"""
        try:
            await asyncio.wait_for(
                ws.send_json(message),
                timeout=SEND_TIMEOUT_SECONDS,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    async def send_to_user(self, user_id: str, message: dict) -> int:
        """把消息只发给该 user 的所有在线连接；返回成功下发的连接数。"""
        async with self._lock:
            targets = list(self._by_user.get(user_id, ()))
        sent = 0
        for ws in targets:
            if await self.send_json(ws, message):
                sent += 1
        return sent

    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    async def subscribe(self, ws: WebSocket, raw_topics: list[str]) -> tuple[set[str], list[str]]:
        """规范化并订阅主题；返回 (current_topics, rejected)。"""
        accepted, rejected = topic_rules.filter_topics(raw_topics)
        async with self._lock:
            if ws not in self._subs:
                return set(), rejected
            current = self._subs[ws]
            room = topic_rules.MAX_TOPICS_PER_CONNECTION - len(current)
            if room <= 0:
                return set(current), rejected + accepted
            for topic in accepted[:room]:
                current.add(topic)
            overflow = accepted[room:]
            if overflow:
                rejected = rejected + overflow
            return set(current), rejected

    async def unsubscribe(self, ws: WebSocket, topics: list[str]) -> set[str]:
        accepted, _ = topic_rules.filter_topics(topics)
        async with self._lock:
            if ws in self._subs:
                self._subs[ws].difference_update(accepted or topics)
                return set(self._subs[ws])
        return set()

    async def snapshot(self) -> list[tuple[WebSocket, set[str]]]:
        async with self._lock:
            return [(ws, set(topics)) for ws, topics in self._subs.items()]

    async def count(self) -> int:
        async with self._lock:
            return len(self._subs)


manager = ConnectionManager()
