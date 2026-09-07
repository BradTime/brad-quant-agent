"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. Phase 0 wires:
health check + ``/api/v1`` (auth/market/dashboard) + CORS + a background
scheduler (data source -> cache) + a ``/ws/v1`` WebSocket that broadcasts the
cached quotes/indices to subscribers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core import redis_client
from app.core.config import settings
from app.core.cors import apply_cors_headers, cors_lan_regex
from app.core.response import error
from app.ws.routes import router as ws_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    role = settings.process_role
    if role == "worker":
        raise RuntimeError("PROCESS_ROLE=worker must run with python -m app.worker")
    from app.runtime import (
        close_shared_state,
        start_api_runtime,
        start_worker_runtime,
        stop_api_runtime,
        stop_worker_runtime,
    )

    api_state = await start_api_runtime()
    worker_state = start_worker_runtime() if role == "all" else None
    try:
        yield
    finally:
        await stop_api_runtime(api_state)
        if worker_state is not None:
            stop_worker_runtime(worker_state)
        await close_shared_state()


def _init_sentry() -> None:
    """仅当配置了 SENTRY_DSN 才初始化（默认关闭、零开销、不外联）。"""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=settings.sentry_traces_sample_rate,
        )
        logger.info("Sentry 已启用（environment=%s）", settings.app_env)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sentry 初始化失败（已忽略）：%s", exc)


_init_sentry()

app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # 局域网放开仅用于开发；生产环境强制关闭（即使误配 cors_allow_private_lan=true）
    allow_origin_regex=(
        cors_lan_regex()
        if (settings.cors_allow_private_lan and not settings.is_production)
        else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

app.include_router(health_router, tags=["health"])
app.include_router(api_router)
app.include_router(ws_router)


@app.middleware("http")
async def ensure_cors_on_all_responses(request: Request, call_next):
    """兜底：ASGI 层未捕获异常或异常响应未走 CORSMiddleware 时仍带 CORS 头。"""
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception("request failed: %s", exc)
        response = error("服务器内部错误", code=500, http_status=500, request=request)
    else:
        apply_cors_headers(request.headers.get("origin"), response)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return error(detail, code=exc.status_code, http_status=exc.status_code, request=request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.debug("validation error: %s", exc.errors())
    return error("请求参数无效", code=400, http_status=400, request=request)


@app.exception_handler(redis_client.SharedStateUnavailable)
async def shared_state_exception_handler(
    request: Request, exc: redis_client.SharedStateUnavailable
):
    return error(str(exc), code=503, http_status=503, request=request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return error("服务器内部错误", code=500, http_status=500, request=request)


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "version": settings.version, "docs": "/docs"}
