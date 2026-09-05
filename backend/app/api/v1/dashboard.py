"""Dashboard endpoints.

Market overview is public cache data. Portfolio endpoints require auth and
aggregate the caller's simulated trading account / positions / trades / strategies.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.response import success
from app.models.user import User
from app.services import dashboard, market

router = APIRouter()


@router.get("/market-overview")
def market_overview() -> dict:
    return success(market.get_market_overview())


@router.get("/stats")
def stats(user: User = Depends(get_current_user)) -> dict:
    return success(dashboard.get_stats(str(user.id)))


@router.get("/return-curve")
def return_curve(days: int = 30, user: User = Depends(get_current_user)) -> dict:
    return success(dashboard.return_curve(str(user.id), days=days))


@router.get("/position-distribution")
def position_distribution(user: User = Depends(get_current_user)) -> dict:
    return success(dashboard.position_distribution(str(user.id)))


@router.get("/recent-trades")
def recent_trades(limit: int = 10, user: User = Depends(get_current_user)) -> dict:
    return success(dashboard.recent_trades(str(user.id), limit=limit))
