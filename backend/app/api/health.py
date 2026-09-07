"""Health / readiness endpoints."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core import redis_client
from app.core.config import settings
from app.core.response import error, success
from app.db.session import engine
from app.services import job_health, quote_cache

router = APIRouter()
logger = logging.getLogger(__name__)
_STARTED_AT = time.monotonic()


@router.get("/health")
def health() -> dict:
    """Liveness：进程活着且数据库可连。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("health database check failed: %s", type(exc).__name__)
        return error("database unavailable", code=503, http_status=503)
    return success({"status": "ok", "database": "ok"}, message="ok")


@router.get("/ready")
def ready() -> dict:
    """Readiness：数据库 +（启用时）调度器与行情缓存新鲜度。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness database check failed: %s", type(exc).__name__)
        return error("database unavailable", code=503, http_status=503)

    role = settings.process_role
    try:
        cache_status = quote_cache.cache.status()
    except redis_client.SharedStateUnavailable:
        cache_status = {"shared": redis_client.enabled(), "available": False}
    payload: dict = {
        "status": "ok",
        "database": "ok",
        "role": role,
        "schedulerEnabled": settings.enable_scheduler,
        "jobs": job_health.snapshot(),
        "quoteCache": cache_status,
    }

    reasons: list[str] = []
    redis_status = redis_client.status()
    redis_ok = bool(redis_status["ok"])
    payload["redis"] = redis_status
    if not redis_ok:
        reasons.append("redis_unavailable")

    if settings.enable_scheduler and role in {"all", "worker"}:
        from app.services.scheduler import scheduler_running

        if redis_client.enabled():
            from app.services.scheduler_leader import (
                scheduler_is_leader,
                scheduler_leader_running,
            )

            payload["schedulerLeaderRunning"] = scheduler_leader_running()
            payload["schedulerLeader"] = scheduler_is_leader()
            payload["schedulerRunning"] = scheduler_running()
            if not scheduler_leader_running():
                reasons.append("scheduler_leader_not_running")
        else:
            payload["schedulerRunning"] = scheduler_running()
            if not scheduler_running():
                reasons.append("scheduler_not_running")
        ok, job_reasons = job_health.is_healthy(
            required_jobs=["refresh_quotes", "refresh_indices"],
            max_consecutive_failures=5,
        )
        if not ok:
            reasons.extend(job_reasons)

    if redis_client.enabled() and role in {"all", "api"}:
        from app.ws.redis_bridge import running as redis_bridge_running

        payload["redisWsSubscriberRunning"] = redis_bridge_running()
        if not redis_bridge_running():
            reasons.append("redis_ws_subscriber_not_running")

    if role == "api" and redis_ok:
        client = redis_client.get_redis()
        try:
            worker_alive = bool(
                client
                and client.exists(redis_client.key("health", "worker", "any"))
            )
            lease_alive = bool(
                client
                and client.exists(redis_client.key("leader", "scheduler"))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("readiness coordination check failed: %s", type(exc).__name__)
            worker_alive = False
            lease_alive = False
        payload["workerHeartbeat"] = worker_alive
        if not worker_alive:
            reasons.append("worker_heartbeat_missing")
        if settings.enable_scheduler or settings.enable_auth_outbox_scheduler:
            payload["schedulerLeadership"] = lease_alive
            if not lease_alive:
                reasons.append("scheduler_leadership_missing")

    if settings.enable_scheduler and role in {"all", "api"}:
        # During startup the elected worker needs time to populate the snapshot.
        now = time.time()
        max_age = max(settings.quote_refresh_seconds, 1) * 5
        stocks_ts = float(cache_status.get("stocks_ts") or 0)
        startup_grace_elapsed = (
            time.monotonic() - _STARTED_AT
        ) >= settings.readiness_startup_grace_seconds
        if stocks_ts <= 0 and startup_grace_elapsed:
            reasons.append("quote_cache_missing")
            payload["quoteCacheMissing"] = True
        elif stocks_ts > 0 and (now - stocks_ts) > max_age:
            reasons.append("quote_cache_stale")
            payload["quoteCacheStale"] = True

    if reasons:
        payload["status"] = "degraded"
        payload["reasons"] = reasons
        return error(
            "service not ready: " + ",".join(reasons),
            code=503,
            http_status=503,
            data=payload,
        )
    return success(payload, message="ok")
