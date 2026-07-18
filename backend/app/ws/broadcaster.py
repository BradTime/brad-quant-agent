"""WebSocket broadcaster.

A single async loop reads the in-memory quote cache (never the network) every
``ws_push_seconds`` and pushes per-topic updates to subscribers. Topics:
- ``market.indices``            -> 指数概览列表
- ``market.quote.<CODE>``       -> 单只个股快照（CODE 为规范代码，如 600000.SH）

慢客户端用发送超时隔离，不串行拖死整轮广播。
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

from app.services import market
from app.ws.manager import manager
from app.ws.topics import TOPIC_INDICES, normalize_topic

logger = logging.getLogger(__name__)

_QUOTE_PREFIX = "market.quote."


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload_for(topic: str, cache: dict):
    if topic == TOPIC_INDICES:
        if "indices" not in cache:
            cache["indices"] = market.indices_snapshot()
        return cache["indices"]
    if topic.startswith(_QUOTE_PREFIX):
        if "quotes" not in cache:
            cache["quotes"] = market.quotes_map_snapshot()
        code = topic[len(_QUOTE_PREFIX) :]
        return cache["quotes"].get(code) or market.get_cached_or_last_quote(code)
    return None


async def _send(ws: WebSocket, topic: str, payload, ts: int) -> None:
    await manager.send_json(
        ws,
        {"type": "update", "topic": topic, "payload": payload, "timestamp": ts},
    )


async def push_to(ws: WebSocket, topics: list[str]) -> None:
    """Immediate push for a single client (used right after it subscribes)."""
    cache: dict = {}
    ts = _now_ms()
    for raw in topics:
        topic = normalize_topic(raw) or raw
        payload = _payload_for(topic, cache)
        if payload is not None:
            await _send(ws, topic, payload, ts)


async def _broadcast_tick() -> None:
    conns = await manager.snapshot()
    if not conns:
        return
    # 预构建只读缓存：本轮所有连接共享，避免慢客户端放大 DB/缓存压力
    cache: dict = {}
    ts = _now_ms()
    # 收集本轮需要的全部主题，先物化 payload
    all_topics: set[str] = set()
    for _, topics in conns:
        all_topics.update(topics)
    payloads = {topic: _payload_for(topic, cache) for topic in all_topics}

    async def _push_one(ws: WebSocket, topics: set[str]) -> None:
        for topic in topics:
            payload = payloads.get(topic)
            if payload is not None:
                await _send(ws, topic, payload, ts)

    await asyncio.gather(
        *[_push_one(ws, topics) for ws, topics in conns],
        return_exceptions=True,
    )


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
