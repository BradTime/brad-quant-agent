"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. Phase 0 wires:
health check + ``/api/v1`` (market/dashboard) + CORS + a background scheduler
that refreshes the in-memory quote cache.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = False
    if settings.enable_scheduler:
        try:
            from app.services.scheduler import start_scheduler

            start_scheduler()
            started = True
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 行情调度器启动失败（已忽略，可手动 ingest）：{exc}")
    yield
    if started:
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


@app.get("/")
def root() -> dict:
    return {"service": settings.app_name, "version": settings.version, "docs": "/docs"}
