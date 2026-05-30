"""Market data endpoints (compatible with the existing frontend market API)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.response import error, success
from app.models.user import User
from app.schemas.market import ScreenRequest
from app.services import market
from app.services import rate_limit as rate_limit_service

router = APIRouter()

_MAX_PAGE_SIZE = 200
_MAX_KLINE_COUNT = 500


@router.get("/quotes")
def quotes(
    page: int = 1, pageSize: int = 20, sortBy: str = "price", sortOrder: str = "desc"
) -> dict:
    page_size = max(1, min(pageSize, _MAX_PAGE_SIZE))
    return success(market.get_quotes(page, page_size, sortBy, sortOrder))


@router.get("/quotes/popular")
def popular(limit: int = 20) -> dict:
    data = market.get_quotes(1, limit, "changePercent", "desc")
    return success(data["stocks"])


@router.get("/quote/{code}")
def quote(code: str) -> dict:
    q = market.get_quote(code)
    if q is None:
        return error("未找到该标的的实时行情", code=404, http_status=404)
    return success(q)


@router.get("/indexes")
def indexes() -> dict:
    return success(market.get_indexes_as_stockquotes())


@router.get("/kline")
def kline(symbol: str, period: str = "day", count: int = 100) -> dict:
    n = max(1, min(count, _MAX_KLINE_COUNT))
    return success(market.get_kline(symbol, period, n))


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
def financials(code: str, limit: int = 12) -> dict:
    return success(market.get_financials(code, limit))


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
def screen(body: ScreenRequest) -> dict:
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
