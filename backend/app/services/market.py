"""Market read service.

Quotes/indices are served from the in-memory cache (falling back to a live
fetch if the cache is cold, e.g. scheduler disabled). K-line and instrument
lookups read from Postgres (ingest first via the CLI).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
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


# 免费实时源（akshare/efinance）是无超时的阻塞网络调用，限流时会无限挂起，
# 拖死调度任务与 HTTP 请求。这里用守护线程 + join 超时做硬降级：超时即返回 None
# （上层据此保持缓存为冷 / 选股返回空，并按 SPEC 标注「实时不可用」）。
# _rt_inflight 记录各类抓取的开始时间：同一类抓取在其超时窗口内不重复发起，
# 把被丢弃的卡死线程数限制在 ~1，源恢复后窗口过期会自动重试（自愈）。
_rt_inflight: dict[str, float] = {}
_rt_lock = threading.Lock()


def _fetch_with_timeout(kind: str, fn, timeout: float, label: str):
    if timeout <= 0:
        return fn()
    now = time.monotonic()
    with _rt_lock:
        started = _rt_inflight.get(kind)
        if started is not None and (now - started) < timeout:
            logger.debug("实时源 %s 上次抓取仍在超时窗口内，跳过本次（降级为空）", label)
            return None
        _rt_inflight[kind] = now

    box: dict = {}

    def runner() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            with _rt_lock:
                if _rt_inflight.get(kind) == now:
                    _rt_inflight.pop(kind, None)

    t = threading.Thread(target=runner, name=f"rt-{kind}", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning("实时源 %s 抓取超时 %.0fs，降级为空", label, timeout)
        return None
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _fetch_quotes() -> list[QuoteDTO]:
    """Try realtime providers in order; first non-empty result wins."""
    timeout = settings.realtime_fetch_timeout_seconds
    for provider in get_providers_for("realtime"):
        try:
            quotes = _fetch_with_timeout(
                "quotes", provider.get_realtime_quotes, timeout, provider.name
            )
            if quotes:
                return quotes
        except Exception as exc:  # noqa: BLE001
            logger.debug("实时行情源 %s 失败: %s", provider.name, exc)
    return []


def _fetch_indices() -> list[QuoteDTO]:
    timeout = settings.realtime_fetch_timeout_seconds
    for provider in get_providers_for("index"):
        try:
            quotes = _fetch_with_timeout(
                "indices",
                lambda p=provider: p.get_index_quotes(settings.index_code_list),
                timeout,
                provider.name,
            )
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


def _last_close_quote(code: str) -> dict | None:
    """Fallback when realtime is unavailable: synthesize a quote from the last two
    daily bars in Postgres (marked ``stale``). Keeps the detail page usable when
    the free realtime snapshot source is rate-limited/down."""
    canonical = code if "." in code else symbols.to_canonical(symbols.to_six(code))
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(DailyBar)
                .where(DailyBar.code == canonical)
                .order_by(DailyBar.trade_date.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
        name_row = session.execute(
            select(Instrument.name).where(Instrument.code == canonical)
        ).scalar_one_or_none()
    if not rows:
        return None
    last = rows[0]
    prev_close = _f(rows[1].close) if len(rows) > 1 else _f(last.open)
    close = _f(last.close)
    change = (close - prev_close) if (close is not None and prev_close) else 0
    change_pct = (change / prev_close * 100) if prev_close else 0
    return {
        "code": canonical,
        "name": name_row or "",
        "price": close or 0,
        "change": round(change, 4) if change else 0,
        "changePercent": round(change_pct, 4) if change_pct else 0,
        "volume": last.volume or 0,
        "amount": _f(last.amount) or 0,
        "high": _f(last.high),
        "low": _f(last.low),
        "open": _f(last.open),
        "yesterdayClose": prev_close,
        "timestamp": int(
            datetime.combine(last.trade_date, datetime.min.time()).timestamp() * 1000
        ),
        "stale": True,
    }


def get_quote(code: str) -> dict | None:
    found = get_quotes_by_codes([code])
    if found:
        return found[0]
    return _last_close_quote(code)


def get_cached_or_last_quote(code: str) -> dict | None:
    """Cache-only realtime, else DB last-close. Never triggers a live network fetch —
    safe for lists/watchlist where blocking on a rate-limited source is unacceptable."""
    canonical = code if "." in code else symbols.to_canonical(symbols.to_six(code))
    cached = quotes_map_snapshot().get(canonical)
    if cached is not None:
        return cached
    return _last_close_quote(canonical)


def get_instrument_name(code: str) -> str:
    """Fast name lookup from the instruments table (no network)."""
    canonical = code if "." in code else symbols.to_canonical(symbols.to_six(code))
    with SessionLocal() as session:
        return (
            session.execute(
                select(Instrument.name).where(Instrument.code == canonical)
            ).scalar_one_or_none()
            or ""
        )


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


def get_stock_profile(code: str) -> dict:
    """个股概览（行业/板块、上市日期、市值等）。实时取，免费源拿不到时返回 {}。"""
    canonical = _canonical(code)
    for provider in get_providers_for("profile"):
        try:
            profile = provider.get_stock_profile(canonical)
            if profile:
                profile.setdefault("source", provider.name)
                return profile
        except Exception as exc:  # noqa: BLE001
            logger.debug("个股概览源 %s 失败: %s", provider.name, exc)
    return {}


_SCREEN_FIELDS = {
    "price": "price",
    "changePercent": "change_percent",
    "volume": "volume",
    "amount": "amount",
}


def screen_stocks(
    filters: dict | None = None,
    limit: int = 50,
    sort_by: str = "changePercent",
    sort_order: str = "desc",
) -> dict:
    """条件选股：基于全市场实时快照过滤（价格/涨跌幅/成交量/成交额区间 + 关键词）。

    免费快照粒度有限，仅做盘面筛选；返回命中列表与命中数。
    """
    filters = filters or {}
    quotes = _ensure_stocks()

    def _ok(q: QuoteDTO) -> bool:
        checks = [
            (filters.get("priceMin"), q.price, "ge"),
            (filters.get("priceMax"), q.price, "le"),
            (filters.get("changePercentMin"), q.change_percent, "ge"),
            (filters.get("changePercentMax"), q.change_percent, "le"),
            (filters.get("volumeMin"), q.volume, "ge"),
            (filters.get("volumeMax"), q.volume, "le"),
            (filters.get("amountMin"), q.amount, "ge"),
            (filters.get("amountMax"), q.amount, "le"),
        ]
        for bound, value, op in checks:
            if bound is None:
                continue
            if value is None:
                return False
            if op == "ge" and value < bound:
                return False
            if op == "le" and value > bound:
                return False
        keyword = (filters.get("keyword") or "").strip()
        if keyword and keyword not in q.name and keyword not in q.code:
            return False
        return True

    matched = [q for q in quotes if _ok(q)]
    key = _SCREEN_FIELDS.get(sort_by, "change_percent")
    matched.sort(key=lambda q: (getattr(q, key) or 0), reverse=(sort_order != "asc"))
    total = len(matched)
    items = matched[: max(1, min(limit, 200))]
    return {"stocks": [_quote_to_stock(q) for q in items], "total": total}


def refresh_stock(code: str, daily_days: int = 400) -> dict:
    """按需为单只股票落库：日K + 资金流 + 财务摘要 + 新闻（用于个股详情页冷启动）。"""
    from datetime import date, timedelta

    from app.services import ingest

    canonical = _canonical(code)
    end = date.today()
    start = end - timedelta(days=daily_days)
    result: dict[str, int | str] = {"code": canonical}
    steps = {
        "daily": lambda: ingest.ingest_daily(
            canonical, start.isoformat(), end.isoformat()
        ),
        "capitalFlow": lambda: ingest.ingest_capital_flow(canonical),
        "financials": lambda: ingest.ingest_financials(canonical),
        "news": lambda: ingest.ingest_news(canonical, 30),
    }
    for name, fn in steps.items():
        try:
            result[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("按需落库 %s.%s 失败: %s", canonical, name, exc)
            result[name] = 0
    return result


def quote_freshness_ms() -> int:
    """缓存快照的更新时间（ms）；0 表示尚无数据。"""
    ts = quote_cache.cache.status().get("stocks_ts") or 0.0
    return int(ts * 1000)


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
