"""WebSocket endpoint ``/ws/v1``.

Protocol (JSON text frames):
- client -> server: ``{"type":"subscribe","payload":{"topics":[...]}}`` /
  ``{"type":"unsubscribe","payload":{"topics":[...]}}`` / ``{"type":"ping"}``
- server -> client: ``{"type":"update","topic","payload","timestamp"}`` /
  ``pong`` / ``subscribed`` / ``unsubscribed`` / ``error`` / ``welcome``

Auth: optional ``?token=`` (access JWT). If provided and invalid, the socket is
closed; if absent, the connection is accepted (read-only market data).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.ws.broadcaster import push_to
from app.ws.manager import manager

router = APIRouter()


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.websocket("/ws/v1")
async def ws_v1(websocket: WebSocket, token: str | None = None) -> None:
    await manager.connect(websocket)

    authed = False
    if token:
        payload = decode_token(token)
        if not payload or payload.get("type") != "access":
            await websocket.send_json(
                {"type": "error", "payload": {"message": "令牌无效或已过期"}, "timestamp": _now_ms()}
            )
            await manager.disconnect(websocket)
            await websocket.close(code=1008)
            return
        # 已鉴权连接绑定 user_id，开启私有定向推送通道（成交回报/通知等）
        await manager.bind_user(websocket, payload.get("sub"))
        authed = True

    await websocket.send_json(
        {
            "type": "welcome",
            "payload": {
                "topics": ["market.indices", "market.quote.<code>"],
                "privateChannel": authed,
            },
            "timestamp": _now_ms(),
        }
    )

    try:
        while True:
            message = await websocket.receive_json()
            await _handle(websocket, message)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001  (malformed frame etc. -> close)
        pass
    finally:
        await manager.disconnect(websocket)


async def _handle(ws: WebSocket, message: object) -> None:
    if not isinstance(message, dict):
        return
    mtype = message.get("type")
    payload = message.get("payload") or {}

    if mtype == "ping":
        await ws.send_json({"type": "pong", "timestamp": _now_ms()})
        return

    if mtype == "subscribe":
        topics = [t for t in (payload.get("topics") or []) if isinstance(t, str)]
        current = await manager.subscribe(ws, topics)
        await ws.send_json(
            {"type": "subscribed", "payload": {"topics": sorted(current)}, "timestamp": _now_ms()}
        )
        await push_to(ws, topics)
        return

    if mtype == "unsubscribe":
        topics = [t for t in (payload.get("topics") or []) if isinstance(t, str)]
        current = await manager.unsubscribe(ws, topics)
        await ws.send_json(
            {"type": "unsubscribed", "payload": {"topics": sorted(current)}, "timestamp": _now_ms()}
        )
        return

    await ws.send_json(
        {"type": "error", "payload": {"message": f"未知消息类型: {mtype}"}, "timestamp": _now_ms()}
    )
