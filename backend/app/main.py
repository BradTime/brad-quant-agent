"""FastAPI application entrypoint.

See repository-root ``SPEC.md`` for the full architecture. This is the Phase 0
skeleton: health check + ``/api/v1`` aggregator + CORS. Business routers
(auth / market / ai / ...) are mounted onto ``api_router`` as they are built.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title=settings.app_name, version=settings.version)

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
