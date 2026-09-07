"""Fan Redis private-event Pub/Sub into API-local WebSocket connections."""

from __future__ import annotations

import asyncio
import json
import logging

from app.core import redis_client
from app.ws.manager import manager

logger = logging.getLogger(__name__)

_running = False
_MAX_MESSAGE_BYTES = 64 * 1024


def running() -> bool:
    return _running


async def listen_private_events() -> None:
    """Reconnect forever; cancellation cleanly closes the Pub/Sub connection."""
    global _running
    delay = 1.0
    while True:
        pubsub = None
        try:
            client = redis_client.get_async_redis()
            if client is None:
                return
            pubsub = client.pubsub()
            await pubsub.subscribe(redis_client.key("ws", "private"))
            _running = True
            delay = 1.0
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if not isinstance(raw, (bytes, str)):
                    continue
                if len(raw) > _MAX_MESSAGE_BYTES:
                    logger.warning("dropping oversized Redis WS event")
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get("v") != 1:
                    continue
                event_id = payload.get("eventId")
                user_id = payload.get("userId")
                event = payload.get("event")
                if (
                    not isinstance(event_id, str)
                    or not event_id
                    or not isinstance(user_id, str)
                    or not user_id
                    or not isinstance(event, dict)
                    or not isinstance(event.get("type"), str)
                    or not isinstance(event.get("payload"), (dict, list, str, int, float, bool, type(None)))
                    or not isinstance(event.get("timestamp"), int)
                ):
                    continue
                await manager.send_to_user(user_id, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _running = False
            logger.warning("Redis WS subscriber reconnecting: %s", type(exc).__name__)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
        finally:
            _running = False
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:  # noqa: BLE001
                    pass
