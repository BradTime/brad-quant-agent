"""WebSocket broadcaster.

A single async loop reads the in-memory quote cache (never the network) every
``ws_push_seconds`` and pushes per-topic updates to subscribers. Topics:
- ``market.indices``            -> 指数概览列表
- ``market.quote.<CODE>``       -> 单只个股快照（CODE 为规范代码，如 600000.SH）
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

from app.services import market
from app.ws.manager import manager

logger = logging.getLogger(__name__)

_QUOTE_PREFIX = "market.quote."


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload_for(topic: str, cache: dict):
    if topic == "market.indices":
        if "indices" not in cache:
            cache["indices"] = market.indices_snapshot()
        return cache["indices"]
    if topic.startswith(_QUOTE_PREFIX):
        if "quotes" not in cache:
            cache["quotes"] = market.quotes_map_snapshot()
        return cache["quotes"].get(topic[len(_QUOTE_PREFIX) :])
    return None


async def _send(ws: WebSocket, topic: str, payload, ts: int) -> None:
    try:
        await ws.send_json(
            {"type": "update", "topic": topic, "payload": payload, "timestamp": ts}
        )
    except Exception:  # noqa: BLE001  (client gone; cleaned up on disconnect)
        pass


async def push_to(ws: WebSocket, topics: list[str]) -> None:
    """Immediate push for a single client (used right after it subscribes)."""
    cache: dict = {}
    ts = _now_ms()
    for topic in topics:
        payload = _payload_for(topic, cache)
        if payload is not None:
            await _send(ws, topic, payload, ts)


async def _broadcast_tick() -> None:
    conns = await manager.snapshot()
    if not conns:
        return
    cache: dict = {}
    ts = _now_ms()
    for ws, topics in conns:
        for topic in topics:
            payload = _payload_for(topic, cache)
            if payload is not None:
                await _send(ws, topic, payload, ts)


async def push_loop() -> None:
    from app.core.config import settings

    interval = max(settings.ws_push_seconds, 1)
    logger.info("WS 推送循环已启动，每 %ss 广播一次", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            await _broadcast_tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("WS 广播失败: %s", exc)
