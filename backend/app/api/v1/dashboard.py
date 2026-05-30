"""Dashboard endpoints.

Phase 1 implements the market overview (indices). Portfolio-related endpoints
(stats / return-curve / position-distribution / recent-trades) belong to the
simulated-trading phase (Phase 3); until then they return **empty placeholders**
(zeros / empty lists) so the legacy dashboard renders gracefully instead of 404.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import success
from app.services import market

router = APIRouter()


@router.get("/market-overview")
def market_overview() -> dict:
    return success(market.get_market_overview())


# ---- Phase 3 占位：尚无模拟交易/持仓时返回空数据，避免前端 404 ----


@router.get("/stats")
def stats() -> dict:
    return success(
        {
            "totalAssets": 0,
            "todayReturn": 0,
            "todayReturnPercent": 0,
            "cumulativeReturn": 0,
            "cumulativeReturnPercent": 0,
            "runningStrategies": 0,
            "totalStrategies": 0,
        }
    )


@router.get("/return-curve")
def return_curve(days: int = 30) -> dict:
    return success([])


@router.get("/position-distribution")
def position_distribution() -> dict:
    return success([])


@router.get("/recent-trades")
def recent_trades(limit: int = 10) -> dict:
    return success([])
