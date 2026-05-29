"""Dashboard endpoints.

Phase 1 only implements the market overview (indices). Portfolio-related
endpoints (stats / return-curve / positions / trades) arrive with the
simulated-trading phase; the frontend tolerates their absence gracefully.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import success
from app.services import market

router = APIRouter()


@router.get("/market-overview")
def market_overview() -> dict:
    return success(market.get_market_overview())
