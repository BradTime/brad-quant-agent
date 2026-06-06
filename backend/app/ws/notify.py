"""私有定向 WS 推送（按 user_id 下发私有事件，区别于 broadcaster 的行情广播）。

用途：Phase 3 模拟交易的**成交回报 / 委托状态 / 持仓变动**，以及面向单个用户的通知，
都复用本通道（私有数据绝不能走广播）。提供两种入口：
- ``notify_user``：async，在协程上下文（如 WS 路由、async 服务）中直接 await；
- ``notify_user_threadsafe``：供**同步**调用方（撮合/调度器线程）安全地投递到应用事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.ws.manager import manager

logger = logging.getLogger(__name__)


def _envelope(event_type: str, payload: object) -> dict:
    return {"type": event_type, "payload": payload, "timestamp": int(time.time() * 1000)}


async def notify_user(user_id: str, event_type: str, payload: object) -> int:
    """向某用户的所有在线连接下发一个私有事件；返回送达连接数。"""
    if not user_id:
        return 0
    return await manager.send_to_user(user_id, _envelope(event_type, payload))


def notify_user_threadsafe(user_id: str, event_type: str, payload: object) -> bool:
    """同步上下文（无事件循环）下投递私有事件到应用事件循环。返回是否成功排程。"""
    loop = manager.loop()
    if loop is None or not user_id:
        return False
    try:
        asyncio.run_coroutine_threadsafe(notify_user(user_id, event_type, payload), loop)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("私有 WS 推送排程失败: %s", exc)
        return False
