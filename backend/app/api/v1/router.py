"""``/api/v1`` aggregator.

Business routers are mounted here as they are implemented (see SPEC Phase 0/1).
The ``/api/v1`` prefix matches the frontend ``NEXT_PUBLIC_API_BASE_URL`` default.
"""

from fastapi import APIRouter

from app.core.response import success

api_router = APIRouter(prefix="/api/v1")


@api_router.get("")
def api_root() -> dict:
    return success({"service": "quant-agent-backend", "phase": "0"}, message="API v1 root")


# 后续在此聚合业务路由，例如：
# from app.api.v1 import auth, market, ai
# api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# api_router.include_router(market.router, prefix="/market", tags=["market"])
# api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
