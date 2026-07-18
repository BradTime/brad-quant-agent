"""``/api/v1`` aggregator.

The ``/api/v1`` prefix matches the frontend ``NEXT_PUBLIC_API_BASE_URL`` default.
Business routers are mounted here as they are implemented.
"""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    backtest,
    brief,
    dashboard,
    market,
    sim,
    strategies,
    watchlist,
)
from app.core.response import success

api_router = APIRouter(prefix="/api/v1")


@api_router.get("")
def api_root() -> dict:
    """能力版本号（非产品 Phase）；供监控/客户端识别 API 契约代际。"""
    return success(
        {
            "service": "quant-agent-backend",
            "apiVersion": "1",
            "capabilities": [
                "auth",
                "market",
                "watchlist",
                "dashboard",
                "ai",
                "brief",
                "strategies",
                "backtest",
                "sim",
            ],
        },
        message="API v1 root",
    )


api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(watchlist.router, prefix="/watchlist", tags=["watchlist"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(brief.router, prefix="/brief", tags=["brief"])
api_router.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
api_router.include_router(sim.router, prefix="/sim", tags=["sim"])
