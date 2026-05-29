"""Market read service.

Quotes/indices are served from the in-memory cache (falling back to a live
fetch if the cache is cold, e.g. scheduler disabled). K-line and instrument
lookups read from Postgres (ingest first via the CLI).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import or_, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.extra import CapitalFlow, DragonTiger, FinancialSummary, NewsItem
from app.models.market import DailyBar, Instrument, MinuteBar
from app.providers import symbols
from app.providers.base import QuoteDTO
from app.providers.registry import get_providers_for
from app.services import quote_cache

logger = logging.getLogger(__name__)

_SORT_KEY = {"price": "price", "changePercent": "change_percent", "volume": "volume"}
_PERIOD_MIN = {"1min": "1", "5min": "5", "15min": "15", "30min": "30", "hour": "60"}


def _f(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _quote_to_stock(q: QuoteDTO) -> dict:
    return {
        "code": q.code,
        "name": q.name,
        "price": q.price or 0,
        "change": q.change or 0,
        "changePercent": q.change_percent or 0,
        "volume": q.volume or 0,
        "amount": q.amount or 0,
        "high": q.high,
        "low": q.low,
        "open": q.open,
        "yesterdayClose": q.prev_close,
        "timestamp": int(q.ts.timestamp() * 1000) if q.ts else 0,
    }


def _fetch_quotes() -> list[QuoteDTO]:
    """Try realtime providers in order; first non-empty result wins."""
    for provider in get_providers_for("realtime"):
        try:
            quotes = provider.get_realtime_quotes()
            if quotes:
                return quotes
        except Exception as exc:  # noqa: BLE001
            logger.debug("实时行情源 %s 失败: %s", provider.name, exc)
    return []


def _fetch_indices() -> list[QuoteDTO]:
    for provider in get_providers_for("index"):
        try:
            quotes = provider.get_index_quotes(settings.index_code_list)
            if quotes:
                return quotes
        except Exception as exc:  # noqa: BLE001
            logger.debug("指数源 %s 失败: %s", provider.name, exc)
    return []


def _ensure_stocks() -> list[QuoteDTO]:
    quotes = quote_cache.cache.get_stocks()
    if not quotes:
        quotes = _fetch_quotes()
        if quotes:
            quote_cache.cache.set_stocks(quotes)
    return quotes


def _ensure_indices() -> list[QuoteDTO]:
    idx = quote_cache.cache.get_indices()
    if not idx:
        idx = _fetch_indices()
        if idx:
            quote_cache.cache.set_indices(idx)
    return idx


def get_quotes(
    page: int = 1, page_size: int = 20, sort_by: str = "price", sort_order: str = "desc"
) -> dict:
    quotes = _ensure_stocks()
    key = _SORT_KEY.get(sort_by, "price")
    quotes = sorted(
        quotes, key=lambda q: (getattr(q, key) or 0), reverse=(sort_order != "asc")
    )
    total = len(quotes)
    start = max(page - 1, 0) * page_size
    items = quotes[start : start + page_size]
    return {
        "stocks": [_quote_to_stock(q) for q in items],
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


def get_quotes_by_codes(codes: list[str]) -> list[dict]:
    _ensure_stocks()
    quotes_map = quotes_map_snapshot()
    out: list[dict] = []
    for code in codes:
        canonical = code if "." in code else symbols.to_canonical(symbols.to_six(code))
        quote = quotes_map.get(canonical)
        if quote is not None:
            out.append(quote)
    return out


def get_quote(code: str) -> dict | None:
    found = get_quotes_by_codes([code])
    return found[0] if found else None


def _index_to_overview(q: QuoteDTO) -> dict:
    return {
        "index": q.code,
        "name": q.name,
        "value": q.price or 0,
        "change": q.change or 0,
        "changePercent": q.change_percent or 0,
    }


def get_market_overview() -> list[dict]:
    return [_index_to_overview(q) for q in _ensure_indices()]


def indices_snapshot() -> list[dict]:
    """Cache-only（不触发实时拉取），可安全用于 WS 异步推送循环。"""
    return [_index_to_overview(q) for q in quote_cache.cache.get_indices()]


def quotes_map_snapshot() -> dict[str, dict]:
    """Cache-only：{canonical_code: stock_quote_dict}。"""
    return {q.code: _quote_to_stock(q) for q in quote_cache.cache.get_stocks()}


def get_indexes_as_stockquotes() -> list[dict]:
    return [_quote_to_stock(q) for q in _ensure_indices()]


def get_kline(symbol: str, period: str = "day", count: int = 100) -> list[dict]:
    canonical = symbol if "." in symbol else symbols.to_canonical(symbol)
    with SessionLocal() as session:
        if period == "day":
            stmt = (
                select(DailyBar)
                .where(DailyBar.code == canonical)
                .order_by(DailyBar.trade_date.desc())
                .limit(count)
            )
            rows = list(session.execute(stmt).scalars().all())[::-1]
            return [
                {
                    "time": r.trade_date.isoformat(),
                    "open": _f(r.open),
                    "high": _f(r.high),
                    "low": _f(r.low),
                    "close": _f(r.close),
                    "volume": r.volume or 0,
                }
                for r in rows
            ]
        period_code = _PERIOD_MIN.get(period, "5")
        stmt = (
            select(MinuteBar)
            .where(MinuteBar.code == canonical, MinuteBar.period == period_code)
            .order_by(MinuteBar.dt.desc())
            .limit(count)
        )
        rows = list(session.execute(stmt).scalars().all())[::-1]
        return [
            {
                "time": r.dt.isoformat(),
                "open": _f(r.open),
                "high": _f(r.high),
                "low": _f(r.low),
                "close": _f(r.close),
                "volume": r.volume or 0,
            }
            for r in rows
        ]


def search_instruments(search: str | None = None, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        stmt = select(Instrument)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(Instrument.code.ilike(like), Instrument.name.ilike(like))
            )
        rows = session.execute(stmt.limit(limit)).scalars().all()
        return [
            {
                "code": r.code,
                "name": r.name,
                "exchange": r.exchange,
                "securityType": r.security_type,
                "status": r.status,
            }
            for r in rows
        ]


def _canonical(code: str) -> str:
    return code if '.' in code else symbols.to_canonical(symbols.to_six(code))


def get_capital_flow(code: str, limit: int = 30) -> list[dict]:
    canonical = _canonical(code)
    with SessionLocal() as session:
        stmt = (
            select(CapitalFlow)
            .where(CapitalFlow.code == canonical)
            .order_by(CapitalFlow.trade_date.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())[::-1]
        return [
            {
                "date": r.trade_date.isoformat(),
                "mainNet": _f(r.main_net),
                "mainNetRatio": _f(r.main_net_ratio),
                "superLargeNet": _f(r.super_large_net),
                "largeNet": _f(r.large_net),
                "mediumNet": _f(r.medium_net),
                "smallNet": _f(r.small_net),
            }
            for r in rows
        ]


def get_financials(code: str, limit: int = 12) -> list[dict]:
    canonical = _canonical(code)
    with SessionLocal() as session:
        stmt = (
            select(FinancialSummary)
            .where(FinancialSummary.code == canonical)
            .order_by(FinancialSummary.report_date.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())
        return [
            {
                "reportDate": r.report_date.isoformat(),
                "eps": _f(r.eps),
                "bps": _f(r.bps),
                "roe": _f(r.roe),
                "revenue": _f(r.revenue),
                "netProfit": _f(r.net_profit),
                "grossMargin": _f(r.gross_margin),
            }
            for r in rows
        ]


def get_dragon_tiger(code: str, limit: int = 20) -> list[dict]:
    canonical = _canonical(code)
    with SessionLocal() as session:
        stmt = (
            select(DragonTiger)
            .where(DragonTiger.code == canonical)
            .order_by(DragonTiger.trade_date.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        return [
            {
                "date": r.trade_date.isoformat(),
                "name": r.name,
                "reason": r.reason,
                "netBuy": _f(r.net_buy),
                "buy": _f(r.buy_amount),
                "sell": _f(r.sell_amount),
            }
            for r in rows
        ]


def get_news(code: str, limit: int = 20) -> list[dict]:
    canonical = _canonical(code)
    with SessionLocal() as session:
        stmt = (
            select(NewsItem)
            .where(NewsItem.code == canonical)
            .order_by(NewsItem.published_at.desc().nullslast())
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
        return [
            {
                "title": r.title,
                "url": r.url,
                "source": r.source_name,
                "publishedAt": r.published_at.isoformat() if r.published_at else None,
                "summary": (r.summary[:200] if r.summary else None),
            }
            for r in rows
        ]


# ---- scheduler jobs (guarded; failures are logged, never crash the loop) ----

def refresh_quotes_job() -> None:
    quotes = _fetch_quotes()
    if quotes:
        quote_cache.cache.set_stocks(quotes)
    else:
        logger.debug("实时行情刷新为空，保留上次缓存")


def refresh_indices_job() -> None:
    quotes = _fetch_indices()
    if quotes:
        quote_cache.cache.set_indices(quotes)
    else:
        logger.debug("指数刷新为空，保留上次缓存")
