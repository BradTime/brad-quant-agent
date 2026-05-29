"""``/api/v1`` aggregator.

The ``/api/v1`` prefix matches the frontend ``NEXT_PUBLIC_API_BASE_URL`` default.
Business routers are mounted here as they are implemented.
"""

from fastapi import APIRouter

from app.api.v1 import ai, auth, dashboard, market
from app.core.response import success

api_router = APIRouter(prefix="/api/v1")


@api_router.get("")
def api_root() -> dict:
    return success({"service": "quant-agent-backend", "phase": "0"}, message="API v1 root")


api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
