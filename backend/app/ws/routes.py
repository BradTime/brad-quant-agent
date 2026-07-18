"""WebSocket endpoint ``/ws/v1``.

Protocol (JSON text frames):
- client -> server: ``{"type":"subscribe","payload":{"topics":[...]}}`` /
  ``{"type":"unsubscribe","payload":{"topics":[...]}}`` / ``{"type":"ping"}``
- server -> client: ``{"type":"update","topic","payload","timestamp"}`` /
  ``pong`` / ``subscribed`` / ``unsubscribed`` / ``error`` / ``welcome``

Auth: optional ``?token=`` (access JWT). If provided and invalid, the socket is
closed; if absent, the connection is accepted (read-only market data).
Authenticated sockets re-validate ``token_version`` on each client message and
close with 1008 after logout / forced revocation.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token, token_version_of
from app.services import auth as auth_service
from app.ws import topics as topic_rules
from app.ws.broadcaster import push_to
from app.ws.manager import manager

router = APIRouter()

# 鉴权连接在每条客户端消息上重验 token_version；登出后下一帧即关闭。


def _now_ms() -> int:
    return int(time.time() * 1000)


def _token_still_valid(user_id: str, token_version: int) -> bool:
    return auth_service.user_matches_token_version(user_id, token_version) is not None


@router.websocket("/ws/v1")
async def ws_v1(websocket: WebSocket, token: str | None = None) -> None:
    await manager.connect(websocket)

    authed = False
    user_id: str | None = None
    token_version: int | None = None

    if token:
        payload = decode_token(token)
        tv = token_version_of(payload)
        subject = str(payload.get("sub")) if payload else ""
        if (
            not payload
            or payload.get("type") != "access"
            or tv is None
            or not subject
            or not _token_still_valid(subject, tv)
        ):
            await manager.send_json(
                websocket,
                {"type": "error", "payload": {"message": "令牌无效或已过期"}, "timestamp": _now_ms()},
            )
            await manager.disconnect(websocket)
            await websocket.close(code=1008)
            return
        # 已鉴权连接绑定 user_id，开启私有定向推送通道（成交回报/通知等）
        await manager.bind_user(websocket, subject)
        authed = True
        user_id = subject
        token_version = tv

    await manager.send_json(
        websocket,
        {
            "type": "welcome",
            "payload": {
                "topics": ["market.indices", "market.quote.<code>"],
                "privateChannel": authed,
                "limits": {
                    "maxTopics": topic_rules.MAX_TOPICS_PER_CONNECTION,
                    "maxSubscribeBatch": topic_rules.MAX_SUBSCRIBE_BATCH,
                },
            },
            "timestamp": _now_ms(),
        },
    )

    try:
        while True:
            message = await websocket.receive_json()
            if (
                authed
                and user_id is not None
                and token_version is not None
                and not _token_still_valid(user_id, token_version)
            ):
                await manager.send_json(
                    websocket,
                    {
                        "type": "error",
                        "payload": {"message": "令牌已失效"},
                        "timestamp": _now_ms(),
                    },
                )
                await websocket.close(code=1008)
                return
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
        await manager.send_json(ws, {"type": "pong", "timestamp": _now_ms()})
        return

    if mtype == "subscribe":
        if not topic_rules.allow_subscribe(id(ws)):
            await manager.send_json(
                ws,
                {
                    "type": "error",
                    "payload": {"message": "订阅过于频繁，请稍后再试"},
                    "timestamp": _now_ms(),
                },
            )
            return
        raw_topics = [t for t in (payload.get("topics") or []) if isinstance(t, str)]
        current, rejected = await manager.subscribe(ws, raw_topics)
        await manager.send_json(
            ws,
            {
                "type": "subscribed",
                "payload": {
                    "topics": sorted(current),
                    "rejected": rejected[:20],
                },
                "timestamp": _now_ms(),
            },
        )
        if current:
            await push_to(ws, sorted(current))
        return

    if mtype == "unsubscribe":
        topics = [t for t in (payload.get("topics") or []) if isinstance(t, str)]
        current = await manager.unsubscribe(ws, topics)
        await manager.send_json(
            ws,
            {
                "type": "unsubscribed",
                "payload": {"topics": sorted(current)},
                "timestamp": _now_ms(),
            },
        )
        return

    await manager.send_json(
        ws,
        {
            "type": "error",
            "payload": {"message": f"未知消息类型: {mtype}"},
            "timestamp": _now_ms(),
        },
    )
