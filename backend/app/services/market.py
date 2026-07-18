"""Market read service.

Quotes/indices are served from the in-memory cache (falling back to a live
fetch if the cache is cold, e.g. scheduler disabled). K-line and instrument
lookups read from Postgres (ingest first via the CLI).
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import threading
import time
from datetime import UTC, date, datetime
from datetime import time as dt_time
from functools import lru_cache

from sqlalchemy import func, inspect, or_, select

from app.core.config import settings
from app.core.tz import MARKET_TZ
from app.core.ohlc import InvalidOHLCError, validate_ohlc, validate_previous_close
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


def _f(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sort_quotes(
    quotes: list[QuoteDTO],
    key: str,
    *,
    descending: bool,
) -> list[QuoteDTO]:
    """Sort finite values while keeping missing values last in either direction."""

    def sort_key(quote: QuoteDTO) -> tuple[int, float]:
        value = _f(getattr(quote, key, None))
        if value is None:
            return (1, 0.0)
        return (0, -value if descending else value)

    return sorted(quotes, key=sort_key)


def _warn_invalid_bar(context: str, exc: InvalidOHLCError) -> None:
    logger.warning(
        "%s code=%s time=%s reason=%s",
        context,
        exc.code,
        exc.bar_time,
        exc.reason,
    )


def _now() -> datetime:
    return datetime.now(MARKET_TZ)


def _as_shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        # 现有免费源返回无时区时间，按其 A 股语义解释为上海本地时间。
        return value.replace(tzinfo=MARKET_TZ)
    return value.astimezone(MARKET_TZ)


@lru_cache(maxsize=1)
def _xshg_calendar():
    import exchange_calendars as xcals

    return xcals.get_calendar("XSHG")


def is_a_share_trading_session(now: datetime | None = None) -> bool:
    """Return whether ``now`` is in an A-share continuous trading session.

    This intentionally models weekdays only. Exchange holidays and exceptional
    closures require a trading calendar and are outside the current P0 gate.
    """

    local = _as_shanghai(now or _now())
    if local.weekday() >= 5:
        return False
    try:
        import pandas as pd

        if not _xshg_calendar().is_session(pd.Timestamp(local.date())):
            return False
    except Exception as exc:  # noqa: BLE001
        # Calendar uncertainty must fail closed for executable trading prices.
        logger.warning("交易日历校验失败，按休市处理: %s", exc)
        return False
    current = local.time().replace(tzinfo=None)
    return (
        dt_time(9, 30) <= current <= dt_time(11, 30)
        or dt_time(13, 0) <= current <= dt_time(15, 0)
    )


def _age_ms(now: datetime, then: datetime) -> int:
    return max(0, int((now - then).total_seconds() * 1000))


def _snapshot_state(
    *,
    price: float | None,
    data_as_of: datetime | None,
    cache_refreshed_at: float | None,
    event_time_reliable: bool = False,
    now: datetime | None = None,
    source: str = "realtime",
) -> dict:
    price = _f(price)
    current = _as_shanghai(now or _now())
    as_of = _as_shanghai(data_as_of) if data_as_of is not None else None
    cache_as_of = (
        datetime.fromtimestamp(cache_refreshed_at, tz=MARKET_TZ)
        if cache_refreshed_at and cache_refreshed_at > 0
        else None
    )
    data_age_ms = _age_ms(current, as_of) if as_of is not None else None
    cache_age_ms = _age_ms(current, cache_as_of) if cache_as_of is not None else None
    observed_ages = [age for age in (data_age_ms, cache_age_ms) if age is not None]
    age_ms = max(observed_ages) if observed_ages else None
    max_age_ms = max(settings.quote_trade_max_age_seconds, 0) * 1000

    stale = False
    reason: str | None = None
    if source == "last_close":
        stale = True
        reason = "last_close"
    elif as_of is None:
        stale = True
        reason = "missing_as_of"
    elif not event_time_reliable:
        stale = True
        reason = "unverified_event_time"
    elif data_age_ms is not None and data_age_ms > max_age_ms:
        stale = True
        reason = "quote_expired"
    elif cache_as_of is None:
        stale = True
        reason = "missing_cache_refresh"
    elif cache_age_ms is not None and cache_age_ms > max_age_ms:
        stale = True
        reason = "cache_expired"
    elif price is None or price <= 0:
        reason = "invalid_price"
    elif not is_a_share_trading_session(current):
        reason = "market_closed"

    return {
        "asOf": int(as_of.timestamp() * 1000) if as_of is not None else None,
        "ageMs": age_ms,
        "maxAgeMs": max_age_ms,
        "stale": stale,
        "staleReason": reason,
        "executable": source == "realtime" and reason is None,
    }


def _quote_to_stock(
    q: QuoteDTO,
    *,
    cache_refreshed_at: float | None = None,
    now: datetime | None = None,
) -> dict:
    price = _f(q.price)
    state = _snapshot_state(
        price=price,
        data_as_of=q.ts,
        cache_refreshed_at=cache_refreshed_at,
        event_time_reliable=q.event_time_reliable,
        now=now,
    )
    return {
        "code": q.code,
        "name": q.name,
        "price": price,
        "change": _f(q.change),
        "changePercent": _f(q.change_percent),
        "volume": _f(q.volume),
        "amount": _f(q.amount),
        "high": _f(q.high),
        "low": _f(q.low),
        "open": _f(q.open),
        "yesterdayClose": _f(q.prev_close),
        # 兼容旧前端；timestamp 与 asOf 同源，绝不是 WS 发送时间。
        "timestamp": state["asOf"] or 0,
        **state,
    }


# 免费实时源（akshare/efinance）是无超时的阻塞网络调用，限流时会无限挂起，
# 拖死调度任务与 HTTP 请求。用有界线程池 + Future.result(timeout) 硬降级：
# 超时即返回 None。inflight 按 provider 分键——主源卡住时备用源仍可发起。
_rt_inflight: dict[str, float] = {}
_rt_lock = threading.Lock()
_rt_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="rt-fetch",
)


def _fetch_with_timeout(kind: str, fn, timeout: float, label: str):
    if not settings.enable_realtime_fetch:
        logger.debug("实时抓取已关闭，跳过 %s", label)
        return None
    if timeout <= 0:
        return fn()
    now = time.monotonic()
    with _rt_lock:
        started = _rt_inflight.get(kind)
        if started is not None and (now - started) < timeout:
            logger.debug("实时源 %s 上次抓取仍在超时窗口内，跳过本次（降级为空）", label)
            return None
        _rt_inflight[kind] = now

    future = _rt_executor.submit(fn)

    def _release(_fut: concurrent.futures.Future, started_at: float = now, key: str = kind) -> None:
        with _rt_lock:
            if _rt_inflight.get(key) == started_at:
                _rt_inflight.pop(key, None)

    future.add_done_callback(_release)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # 保留 inflight 至 done_callback / 超时窗口结束，避免卡死任务仍占池时继续开新抓取
        logger.warning("实时源 %s 抓取超时 %.0fs，降级为空", label, timeout)
        return None



def _fetch_quotes() -> list[QuoteDTO]:
    """Try realtime providers in order; first non-empty result wins."""
    timeout = settings.realtime_fetch_timeout_seconds
    for provider in get_providers_for("realtime"):
        try:
            quotes = _fetch_with_timeout(
                f"quotes:{provider.name}",
                provider.get_realtime_quotes,
                timeout,
                provider.name,
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
                f"indices:{provider.name}",
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
    _, cache_refreshed_at = quote_cache.cache.get_stocks_snapshot()
    key = _SORT_KEY.get(sort_by, "price")
    quotes = _sort_quotes(
        quotes,
        key,
        descending=sort_order != "asc",
    )
    total = len(quotes)
    start = max(page - 1, 0) * page_size
    items = quotes[start : start + page_size]
    return {
        "stocks": [
            _quote_to_stock(q, cache_refreshed_at=cache_refreshed_at) for q in items
        ],
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
    try:
        checked = validate_ohlc(
            open_value=last.open,
            high_value=last.high,
            low_value=last.low,
            close_value=last.close,
            volume=last.volume,
            amount=last.amount,
            code=canonical,
            bar_time=last.trade_date,
        )
    except InvalidOHLCError as exc:
        _warn_invalid_bar("拒绝非法最近收盘行情", exc)
        return None
    prev_close = None
    if len(rows) > 1:
        try:
            prev_close = validate_previous_close(
                rows[1].close,
                code=canonical,
                bar_time=getattr(rows[1], "trade_date", None),
            )
        except InvalidOHLCError as exc:
            _warn_invalid_bar("忽略非法昨收", exc)
    change = checked.close - prev_close if prev_close is not None else None
    change_pct = change / prev_close * 100 if prev_close is not None else None
    close = float(checked.close)
    as_of = datetime.combine(last.trade_date, dt_time(15, 0), tzinfo=MARKET_TZ)
    state = _snapshot_state(
        price=close,
        data_as_of=as_of,
        cache_refreshed_at=None,
        source="last_close",
    )
    return {
        "code": canonical,
        "name": name_row or "",
        "price": close,
        "change": float(round(change, 4)) if change is not None else None,
        "changePercent": (
            float(round(change_pct, 4)) if change_pct is not None else None
        ),
        "volume": float(checked.volume) if checked.volume is not None else None,
        "amount": float(checked.amount) if checked.amount is not None else None,
        "high": float(checked.high),
        "low": float(checked.low),
        "open": float(checked.open),
        "yesterdayClose": float(prev_close) if prev_close is not None else None,
        "timestamp": state["asOf"] or 0,
        **state,
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


def get_instrument_list_date(code: str) -> date | None:
    """Fast listing-date lookup from the instruments table (no network)."""
    canonical = code if "." in code else symbols.to_canonical(symbols.to_six(code))
    with SessionLocal() as session:
        if not inspect(session.get_bind()).has_table(Instrument.__tablename__):
            return None
        return session.execute(
            select(Instrument.list_date).where(Instrument.code == canonical)
        ).scalar_one_or_none()


def _index_to_overview(q: QuoteDTO, *, cache_refreshed_at: float | None = None) -> dict:
    stock = _quote_to_stock(q, cache_refreshed_at=cache_refreshed_at)
    return {
        "index": q.code,
        "name": q.name,
        "value": stock["price"],
        "change": stock["change"],
        "changePercent": stock["changePercent"],
        "timestamp": stock["timestamp"],
        "asOf": stock["asOf"],
        "ageMs": stock["ageMs"],
        "maxAgeMs": stock["maxAgeMs"],
        "stale": stock["stale"],
        "staleReason": stock["staleReason"],
        "executable": stock["executable"],
    }


def get_market_overview() -> list[dict]:
    quotes = _ensure_indices()
    _, cache_refreshed_at = quote_cache.cache.get_indices_snapshot()
    return [
        _index_to_overview(q, cache_refreshed_at=cache_refreshed_at) for q in quotes
    ]


def indices_snapshot() -> list[dict]:
    """Cache-only（不触发实时拉取），可安全用于 WS 异步推送循环。"""
    quotes, cache_refreshed_at = quote_cache.cache.get_indices_snapshot()
    return [
        _index_to_overview(q, cache_refreshed_at=cache_refreshed_at) for q in quotes
    ]


def quotes_map_snapshot() -> dict[str, dict]:
    """Cache-only：{canonical_code: stock_quote_dict}。"""
    quotes, cache_refreshed_at = quote_cache.cache.get_stocks_snapshot()
    return {
        q.code: _quote_to_stock(q, cache_refreshed_at=cache_refreshed_at)
        for q in quotes
    }


def get_indexes_as_stockquotes() -> list[dict]:
    quotes = _ensure_indices()
    _, cache_refreshed_at = quote_cache.cache.get_indices_snapshot()
    return [
        _quote_to_stock(q, cache_refreshed_at=cache_refreshed_at) for q in quotes
    ]


def _collect_valid_kline_rows(
    session,
    stmt,
    *,
    code: str,
    time_field: str,
    count: int,
) -> dict:
    target = max(0, count)
    if target == 0:
        return {"bars": [], "dataQuality": "missing"}
    newest_bars: list[dict] = []
    invalid = False
    offset = 0
    batch_size = max(32, min(target * 2, 500))
    while len(newest_bars) < target:
        rows = list(
            session.execute(stmt.offset(offset).limit(batch_size)).scalars().all()
        )
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            bar_time = getattr(row, time_field)
            try:
                checked = validate_ohlc(
                    open_value=row.open,
                    high_value=row.high,
                    low_value=row.low,
                    close_value=row.close,
                    volume=row.volume,
                    amount=row.amount,
                    code=code,
                    bar_time=bar_time,
                )
            except InvalidOHLCError as exc:
                invalid = True
                _warn_invalid_bar("过滤非法历史行情", exc)
                continue
            newest_bars.append(
                {
                    "time": bar_time.isoformat(),
                    "open": float(checked.open),
                    "high": float(checked.high),
                    "low": float(checked.low),
                    "close": float(checked.close),
                    "volume": (
                        float(checked.volume)
                        if checked.volume is not None
                        else None
                    ),
                }
            )
            if len(newest_bars) == target:
                break
        if len(rows) < batch_size:
            break
    quality = (
        "invalid_ohlc"
        if invalid
        else ("full" if newest_bars else "missing")
    )
    return {"bars": list(reversed(newest_bars)), "dataQuality": quality}


def get_kline(symbol: str, period: str = "day", count: int = 100) -> dict:
    canonical = symbol if "." in symbol else symbols.to_canonical(symbol)
    with SessionLocal() as session:
        if period == "day":
            stmt = (
                select(DailyBar)
                .where(DailyBar.code == canonical)
                .order_by(DailyBar.trade_date.desc())
            )
            return _collect_valid_kline_rows(
                session,
                stmt,
                code=canonical,
                time_field="trade_date",
                count=count,
            )
        period_code = _PERIOD_MIN.get(period, "5")
        stmt = (
            select(MinuteBar)
            .where(MinuteBar.code == canonical, MinuteBar.period == period_code)
            .order_by(MinuteBar.dt.desc())
        )
        return _collect_valid_kline_rows(
            session,
            stmt,
            code=canonical,
            time_field="dt",
            count=count,
        )


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


def get_financials(
    code: str,
    limit: int = 12,
    as_of: datetime | None = None,
) -> list[dict]:
    """Return the latest available vintage for each report date.

    ``as_of`` is an absolute instant. API date-only and timezone interpretation
    is handled at the transport boundary.
    """
    canonical = _canonical(code)
    with SessionLocal() as session:
        filters = [FinancialSummary.code == canonical]
        if as_of is not None:
            filters.append(FinancialSummary.available_at <= _as_utc(as_of))
        ranked = (
            select(
                *FinancialSummary.__table__.columns,
                func.row_number()
                .over(
                    partition_by=FinancialSummary.report_date,
                    order_by=(
                        FinancialSummary.available_at.desc(),
                        FinancialSummary.fetched_at.desc(),
                        FinancialSummary.id.desc(),
                    ),
                )
                .label("vintage_rank"),
            )
            .where(*filters)
            .subquery()
        )
        stmt = (
            select(ranked)
            .where(ranked.c.vintage_rank == 1)
            .order_by(ranked.c.report_date.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).mappings())
        return [
            {
                "reportDate": r["report_date"].isoformat(),
                "eps": _f(r["eps"]),
                "bps": _f(r["bps"]),
                "roe": _f(r["roe"]),
                "revenue": _f(r["revenue"]),
                "netProfit": _f(r["net_profit"]),
                "grossMargin": _f(r["gross_margin"]),
                "announcedAt": (
                    _as_utc(r["announced_at"]).isoformat()
                    if r["announced_at"] is not None
                    else None
                ),
                "availableAt": _as_utc(r["available_at"]).isoformat(),
                "availabilityQuality": (
                    (
                        "source_announced_date_close"
                        if _as_utc(r["available_at"]) > _as_utc(r["announced_at"])
                        else "source_announced_at"
                    )
                    if r["announced_at"] is not None
                    else "first_observed_at"
                ),
                "source": r["source"],
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
            logger.warning(
                "个股概览源 %s 不可用 code=%s: %s",
                provider.name,
                canonical,
                exc,
                exc_info=True,
            )
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
    normalized = [
        (
            quote,
            {
                field: _f(getattr(quote, field, None))
                for field in _SCREEN_FIELDS.values()
            },
        )
        for quote in quotes
    ]
    sort_key = _SCREEN_FIELDS.get(sort_by, "change_percent")

    def _ok(q: QuoteDTO, values: dict[str, float | None]) -> bool:
        checks = [
            (filters.get("priceMin"), values["price"], "ge"),
            (filters.get("priceMax"), values["price"], "le"),
            (
                filters.get("changePercentMin"),
                values["change_percent"],
                "ge",
            ),
            (
                filters.get("changePercentMax"),
                values["change_percent"],
                "le",
            ),
            (filters.get("volumeMin"), values["volume"], "ge"),
            (filters.get("volumeMax"), values["volume"], "le"),
            (filters.get("amountMin"), values["amount"], "ge"),
            (filters.get("amountMax"), values["amount"], "le"),
        ]
        for raw_bound, value, op in checks:
            if raw_bound is None:
                continue
            bound = _f(raw_bound)
            if bound is None or value is None:
                return False
            if op == "ge" and value < bound:
                return False
            if op == "le" and value > bound:
                return False
        keyword = (filters.get("keyword") or "").strip()
        if keyword and keyword not in q.name and keyword not in q.code:
            return False
        return True

    matched = [
        (quote, values)
        for quote, values in normalized
        if values[sort_key] is not None and _ok(quote, values)
    ]
    matched.sort(
        key=lambda item: item[1][sort_key],
        reverse=sort_order != "asc",
    )
    total = len(matched)
    items = [quote for quote, _ in matched[: max(1, min(limit, 200))]]
    _, cache_refreshed_at = quote_cache.cache.get_stocks_snapshot()
    return {
        "stocks": [
            _quote_to_stock(q, cache_refreshed_at=cache_refreshed_at) for q in items
        ],
        "total": total,
    }


def refresh_stock(code: str, daily_days: int = 400) -> dict:
    """按需回填单只股票，并复用完整 ingestion run/锁协议。"""
    from datetime import date, timedelta

    from app.services import ingest

    canonical = _canonical(code)
    end = date.today()
    start = end - timedelta(days=daily_days)
    stats = ingest.backfill_codes(
        [canonical],
        start.isoformat(),
        end.isoformat(),
        include_dragon_tiger=True,
    )
    run = (stats.get("runs") or [{}])[0]
    return {
        "code": canonical,
        "daily": stats["daily"],
        "adjust": stats["adjust"],
        "capitalFlow": stats["capital_flow"],
        "financials": stats["financials"],
        "news": stats["news"],
        "dragonTiger": stats.get("dragon_tiger", 0),
        "errors": stats["errors"],
        "runId": run.get("id"),
        "runStatus": run.get("status"),
        "failedDatasets": run.get("failedDatasets") or [],
    }


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
