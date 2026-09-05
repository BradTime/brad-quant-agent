"""Lazy Redis clients shared by cache, rate limits, pub/sub, and leadership."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_sync_client: Any | None = None
_async_client: Any | None = None
_client_lock = threading.Lock()
_last_error: str | None = None
_last_success_at: float | None = None


class SharedStateUnavailable(RuntimeError):
    """Raised when required cross-replica coordination is unavailable."""


def required() -> bool:
    return bool(
        settings.redis_required
        or settings.process_role in {"api", "worker"}
        or (settings.is_production and enabled())
    )


def enabled() -> bool:
    return bool(settings.redis_url.strip())


def key(*parts: object) -> str:
    suffix = ":".join(str(part).strip().replace(":", "_") for part in parts)
    return f"{settings.redis_key_prefix}:{suffix}"


def get_redis():
    global _sync_client
    if not enabled():
        return None
    if _sync_client is None:
        with _client_lock:
            if _sync_client is None:
                import redis

                _sync_client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=False,
                    socket_connect_timeout=settings.redis_socket_timeout_seconds,
                    socket_timeout=settings.redis_socket_timeout_seconds,
                    health_check_interval=30,
                )
    return _sync_client


def get_async_redis():
    global _async_client
    if not enabled():
        return None
    if _async_client is None:
        import redis.asyncio as redis_async

        _async_client = redis_async.Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            # Pub/Sub listen is intentionally long-lived; a read timeout would
            # force needless reconnects whenever the channel is quiet.
            socket_timeout=None,
            health_check_interval=30,
        )
    return _async_client


def ping() -> tuple[bool, str | None]:
    global _last_error, _last_success_at
    if not enabled():
        return (not required()), (
            "redis_not_configured" if required() else None
        )
    try:
        client = get_redis()
        ok = bool(client and client.ping())
        if ok:
            import time

            _last_success_at = time.time()
            _last_error = None
            return True, None
        _last_error = "ping_failed"
        return False, _last_error
    except Exception as exc:  # noqa: BLE001
        _last_error = type(exc).__name__
        logger.warning("Redis ping failed: %s", _last_error)
        return False, _last_error


def status() -> dict[str, object]:
    ok, error = ping()
    return {
        "enabled": enabled(),
        "required": required(),
        "ok": ok,
        "error": error,
        "lastSuccessAt": _last_success_at,
    }


def unavailable(operation: str, exc: Exception | None = None) -> SharedStateUnavailable:
    error_type = type(exc).__name__ if exc is not None else "not_configured"
    logger.warning("required Redis operation failed (%s): %s", operation, error_type)
    return SharedStateUnavailable("共享状态服务暂不可用，请稍后再试")


def ensure_available() -> None:
    if required() and not ping()[0]:
        raise unavailable("availability_check")


async def close_async_client() -> None:
    global _async_client
    client = _async_client
    _async_client = None
    if client is not None:
        result = client.aclose()
        if asyncio.iscoroutine(result):
            await result


def close_sync_client() -> None:
    global _sync_client
    client = _sync_client
    _sync_client = None
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
