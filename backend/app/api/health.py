"""Health / readiness endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.response import error, success
from app.db.session import engine
from app.services import job_health, quote_cache

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness：进程活着且数据库可连。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return error(f"database unavailable: {exc}", code=503, http_status=503)
    return success({"status": "ok", "database": "ok"}, message="ok")


@router.get("/ready")
def ready() -> dict:
    """Readiness：数据库 +（启用时）调度器与行情缓存新鲜度。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return error(f"database unavailable: {exc}", code=503, http_status=503)

    payload: dict = {
        "status": "ok",
        "database": "ok",
        "schedulerEnabled": settings.enable_scheduler,
        "jobs": job_health.snapshot(),
        "quoteCache": quote_cache.cache.status(),
    }

    reasons: list[str] = []
    if settings.enable_scheduler:
        from app.services.scheduler import scheduler_running

        payload["schedulerRunning"] = scheduler_running()
        if not scheduler_running():
            reasons.append("scheduler_not_running")
        ok, job_reasons = job_health.is_healthy(
            required_jobs=["refresh_quotes", "refresh_indices"],
            max_consecutive_failures=5,
        )
        if not ok:
            reasons.extend(job_reasons)

        # 行情缓存过旧（超过 5 倍刷新周期）视为未就绪；冷启动无数据不算失败
        cache_status = quote_cache.cache.status()
        now = time.time()
        max_age = max(settings.quote_refresh_seconds, 1) * 5
        stocks_ts = float(cache_status.get("stocks_ts") or 0)
        if stocks_ts > 0 and (now - stocks_ts) > max_age:
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
