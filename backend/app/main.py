"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. Phase 0 wires:
health check + ``/api/v1`` (auth/market/dashboard) + CORS + a background
scheduler (data source -> cache) + a ``/ws/v1`` WebSocket that broadcasts the
cached quotes/indices to subscribers.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

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
    role = (settings.process_role or "all").strip().lower()
    run_background = role in {"all", "worker"}
    scheduler_started = False
    outbox_scheduler_started = False
    if settings.enable_scheduler and run_background:
        try:
            from app.services.scheduler import start_scheduler

            start_scheduler()
            scheduler_started = True
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 行情调度器启动失败（已忽略，可手动 ingest）：{exc}")
    elif settings.enable_scheduler and role == "api":
        logger.info("process_role=api：跳过行情调度器（由 worker 进程负责）")

    if settings.enable_auth_outbox_scheduler and run_background:
        try:
            from app.services.verification_outbox import start_outbox_scheduler

            start_outbox_scheduler()
            outbox_scheduler_started = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("认证邮件 outbox 调度器启动失败：%s", type(exc).__name__)

    # RAG：后台预热本地 embedding 模型（守护线程，不阻塞启动；离线/失败自动降级）
    if settings.rag_enabled and settings.embedding_warm_on_start and run_background:
        try:
            from app.ai import embeddings

            embeddings.warm_in_background()
        except Exception as exc:  # noqa: BLE001
            logger.warning("embedding 预热启动失败（已忽略）：%s", exc)
    elif settings.embedding_warm_on_start and role == "api":
        logger.info("process_role=api：跳过 embedding 预热")

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
    if outbox_scheduler_started:
        from app.services.verification_outbox import shutdown_outbox_scheduler

        shutdown_outbox_scheduler()


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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return error("服务器内部错误", code=500, http_status=500, request=request)


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "version": settings.version, "docs": "/docs"}
