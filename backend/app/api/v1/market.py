"""Market data endpoints (compatible with the existing frontend market API)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.asof import parse_as_of
from app.core.response import error, success
from app.models.user import User
from app.schemas.market import ScreenRequest
from app.services import market
from app.services import rate_limit as rate_limit_service

router = APIRouter()

_MAX_PAGE_SIZE = 200
_MAX_KLINE_COUNT = 500


def _parse_financial_as_of(value: str | None) -> datetime | None:
    """Compatibility wrapper around the shared API/AI PIT parser."""
    try:
        return parse_as_of(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="asOf 必须是 RFC3339 或 ISO 日期") from exc


@router.get("/quotes")
def quotes(
    page: int = 1,
    pageSize: int = 20,
    sortBy: str = "price",
    sortOrder: str = "desc",
    _user: User = Depends(get_current_user),
) -> dict:
    page_size = max(1, min(pageSize, _MAX_PAGE_SIZE))
    return success(market.get_quotes(page, page_size, sortBy, sortOrder))


@router.get("/quotes/popular")
def popular(limit: int = 20, _user: User = Depends(get_current_user)) -> dict:
    data = market.get_quotes(1, limit, "changePercent", "desc")
    return success(data["stocks"])


@router.get("/quote/{code}")
def quote(code: str, _user: User = Depends(get_current_user)) -> dict:
    q = market.get_quote(code)
    if q is None:
        return error("未找到该标的的实时行情", code=404, http_status=404)
    return success(q)


@router.get("/indexes")
def indexes(_user: User = Depends(get_current_user)) -> dict:
    return success(market.get_indexes_as_stockquotes())


@router.get("/kline")
def kline(symbol: str, period: str = "day", count: int = 100) -> dict:
    n = max(1, min(count, _MAX_KLINE_COUNT))
    result = market.get_kline(symbol, period, n)
    return success(result)


@router.get("/instruments")
def instruments(search: str | None = None, limit: int = 50) -> dict:
    return success(market.search_instruments(search, limit))


@router.get("/stock/{code}")
def stock_profile(code: str) -> dict:
    return success(market.get_stock_profile(code))


@router.get("/capital-flow")
def capital_flow(code: str, limit: int = 30) -> dict:
    return success(market.get_capital_flow(code, limit))


@router.get("/financials")
def financials(code: str, limit: int = 12, asOf: str | None = None) -> dict:
    return success(market.get_financials(code, limit, _parse_financial_as_of(asOf)))


@router.get("/dragon-tiger")
def dragon_tiger(code: str, limit: int = 20) -> dict:
    return success(market.get_dragon_tiger(code, limit))


@router.get("/news")
def news(code: str, limit: int = 20) -> dict:
    return success(market.get_news(code, limit))


@router.get("/freshness")
def freshness() -> dict:
    return success({"quotesTs": market.quote_freshness_ms()})


@router.post("/screen")
def screen(body: ScreenRequest, _user: User = Depends(get_current_user)) -> dict:
    return success(
        market.screen_stocks(
            body.filters or {}, body.limit, body.sortBy, body.sortOrder
        )
    )


@router.post("/refresh/{code}")
def refresh(code: str, user: User = Depends(get_current_user)) -> dict:
    uid = str(user.id)
    wait = rate_limit_service.seconds_until_refresh_allowed(uid, code)
    if wait is not None:
        return error(
            f"刷新过于频繁，请 {int(wait) + 1} 秒后再试",
            code=429,
            http_status=429,
        )
    result = market.refresh_stock(code)
    rate_limit_service.mark_refresh(uid, code)
    return success(result)
