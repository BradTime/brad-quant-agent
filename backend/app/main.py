"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. Phase 0 wires:
health check + ``/api/v1`` (auth/market/dashboard) + CORS + a background
scheduler (data source -> cache) + a ``/ws/v1`` WebSocket that broadcasts the
cached quotes/indices to subscribers.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.cors import apply_cors_headers, cors_lan_regex
from app.core.response import error
from app.ws.routes import router as ws_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_started = False
    if settings.enable_scheduler:
        try:
            from app.services.scheduler import start_scheduler

            start_scheduler()
            scheduler_started = True
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 行情调度器启动失败（已忽略，可手动 ingest）：{exc}")

    from app.ws.broadcaster import push_loop

    push_task = asyncio.create_task(push_loop())

    yield

    push_task.cancel()
    try:
        await push_task
    except asyncio.CancelledError:
        pass
    if scheduler_started:
        from app.services.scheduler import shutdown_scheduler

        shutdown_scheduler()


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=cors_lan_regex() if settings.cors_allow_private_lan else None,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return error("服务器内部错误", code=500, http_status=500, request=request)


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "version": settings.version, "docs": "/docs"}
