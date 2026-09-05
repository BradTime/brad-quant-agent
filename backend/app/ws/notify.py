"""私有定向 WS 推送（按 user_id 下发私有事件，区别于 broadcaster 的行情广播）。

用途：Phase 3 模拟交易的**成交回报 / 委托状态 / 持仓变动**，以及面向单个用户的通知，
都复用本通道（私有数据绝不能走广播）。提供两种入口：
- ``notify_user``：async，在协程上下文（如 WS 路由、async 服务）中直接 await；
- ``notify_user_threadsafe``：供**同步**调用方（撮合/调度器线程）安全地投递到应用事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from app.core import redis_client
from app.ws.manager import manager

logger = logging.getLogger(__name__)

# 私有事件类型（与行情 ``update`` 分型；前端按 type 判别）
TRADE_FILL = "trade.fill"


def _envelope(event_type: str, payload: object) -> dict:
    return {"type": event_type, "payload": payload, "timestamp": int(time.time() * 1000)}


def _redis_payload(user_id: str, event: dict) -> bytes:
    return json.dumps(
        {"v": 1, "eventId": uuid4().hex, "userId": user_id, "event": event},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode()


async def notify_user(user_id: str, event_type: str, payload: object) -> int:
    """向某用户的所有在线连接下发一个私有事件；返回送达连接数。"""
    if not user_id:
        return 0
    event = _envelope(event_type, payload)
    client = redis_client.get_async_redis()
    if client is not None:
        try:
            return int(
                await client.publish(
                    redis_client.key("ws", "private"),
                    _redis_payload(user_id, event),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis private WS publish failed: %s", type(exc).__name__)
            if redis_client.required():
                return 0
    return await manager.send_to_user(user_id, event)


def _observe_future(fut: object) -> None:
    try:
        result = getattr(fut, "result", None)
        delivered = result() if callable(result) else None
        if delivered == 0:
            logger.debug("私有 WS 推送：用户当前无在线连接")
    except Exception as exc:  # noqa: BLE001
        logger.warning("私有 WS 推送失败: %s", exc)


def notify_user_threadsafe(user_id: str, event_type: str, payload: object) -> bool:
    """同步上下文（无事件循环）下投递私有事件到应用事件循环。返回是否成功排程。"""
    if not user_id:
        return False
    event = _envelope(event_type, payload)
    client = redis_client.get_redis()
    if client is not None:
        try:
            client.publish(
                redis_client.key("ws", "private"),
                _redis_payload(user_id, event),
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis private WS publish failed: %s", type(exc).__name__)
            if redis_client.required():
                return False
    loop = manager.loop()
    if loop is None:
        return False
    coroutine = manager.send_to_user(user_id, event)
    try:
        fut = asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception as exc:  # noqa: BLE001
        # Scheduling can fail when the application loop is closing. The
        # coroutine has not been transferred to a task in that case and must
        # be closed explicitly to avoid a RuntimeWarning/resource leak.
        coroutine.close()
        logger.warning("私有 WS 推送排程失败: %s", exc)
        return False
    fut.add_done_callback(_observe_future)
    return True
