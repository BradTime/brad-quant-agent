"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. Phase 0 wires:
health check + ``/api/v1`` (auth/market/dashboard) + CORS + a background
scheduler (data source -> cache) + a ``/ws/v1`` WebSocket that broadcasts the
cached quotes/indices to subscribers.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.response import error
from app.ws.routes import router as ws_router


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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["health"])
app.include_router(api_router)
app.include_router(ws_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    _ = request
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return error(detail, code=exc.status_code, http_status=exc.status_code)


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "version": settings.version, "docs": "/docs"}
