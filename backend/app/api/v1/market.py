"""Market data endpoints (compatible with the existing frontend market API)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import success
from app.services import market

router = APIRouter()


@router.get("/quotes")
def quotes(
    page: int = 1, pageSize: int = 20, sortBy: str = "price", sortOrder: str = "desc"
) -> dict:
    return success(market.get_quotes(page, pageSize, sortBy, sortOrder))


@router.get("/quotes/popular")
def popular(limit: int = 20) -> dict:
    data = market.get_quotes(1, limit, "changePercent", "desc")
    return success(data["stocks"])


@router.get("/indexes")
def indexes() -> dict:
    return success(market.get_indexes_as_stockquotes())


@router.get("/kline")
def kline(symbol: str, period: str = "day", count: int = 100) -> dict:
    return success(market.get_kline(symbol, period, count))


@router.get("/instruments")
def instruments(search: str | None = None, limit: int = 50) -> dict:
    return success(market.search_instruments(search, limit))
