"""WebSocket connection manager: tracks clients and their topic subscriptions."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._subs: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._subs[ws] = set()

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.pop(ws, None)

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
