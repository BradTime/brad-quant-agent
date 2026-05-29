"""Ingestion: pull from a provider and upsert into Postgres.

Upserts use PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` so re-runs are
idempotent. Realtime quotes are not persisted here (transient); ``fetch_quotes``
just returns them for connectivity checks / API serving.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.numeric import to_decimal, to_int
from app.db.session import SessionLocal
from app.models.extra import CapitalFlow, DragonTiger, FinancialSummary, NewsItem
from app.models.market import AdjustFactor, DailyBar, Instrument, MinuteBar
from app.providers.base import QuoteDTO
from app.providers.registry import get_provider, get_provider_for


def _now():
    return datetime.now(timezone.utc)


def _resolve(provider_name: str | None, capability: str):
    return get_provider(provider_name) if provider_name else get_provider_for(capability)


def _upsert(
    session: Session,
    model,
    rows: list[dict],
    index_elements: list[str],
    update_cols: list[str],
) -> int:
    if not rows:
        return 0
    # 同一批次内相同冲突键只保留最后一条，避免 ON CONFLICT 二次影响同一行报错。
    deduped: dict[tuple, dict] = {}
    for row in rows:
        deduped[tuple(row[c] for c in index_elements)] = row
    values = list(deduped.values())
    stmt = pg_insert(model).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={c: getattr(stmt.excluded, c) for c in update_cols},
    )
    session.execute(stmt)
    return len(values)


def ingest_instruments(provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "instruments")
    items = provider.get_instruments()
    now = _now()
    rows = [
        {
            "code": i.code,
            "name": i.name,
            "exchange": i.exchange,
            "security_type": i.security_type,
            "list_date": i.list_date,
            "delist_date": i.delist_date,
            "status": i.status,
            "source": provider.name,
            "fetched_at": now,
        }
        for i in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            Instrument,
            rows,
            ["code"],
            ["name", "exchange", "security_type", "list_date", "delist_date", "status", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_daily(
    code: str, start: str, end: str, adjust: str = "none", provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "daily")
    bars = provider.get_daily_bars(code, start, end, adjust=adjust)
    now = _now()
    rows = [
        {
            "code": b.code,
            "trade_date": b.dt.date(),
            "open": to_decimal(b.open),
            "high": to_decimal(b.high),
            "low": to_decimal(b.low),
            "close": to_decimal(b.close),
            "volume": to_int(b.volume),
            "amount": to_decimal(b.amount),
            "source": provider.name,
            "fetched_at": now,
        }
        for b in bars
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            DailyBar,
            rows,
            ["code", "trade_date"],
            ["open", "high", "low", "close", "volume", "amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_minute(
    code: str, period: str, start: str, end: str, provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "minute")
    bars = provider.get_minute_bars(code, period, start, end)
    now = _now()
    rows = [
        {
            "code": b.code,
            "dt": b.dt,
            "period": b.period,
            "open": to_decimal(b.open),
            "high": to_decimal(b.high),
            "low": to_decimal(b.low),
            "close": to_decimal(b.close),
            "volume": to_int(b.volume),
            "amount": to_decimal(b.amount),
            "source": provider.name,
            "fetched_at": now,
        }
        for b in bars
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            MinuteBar,
            rows,
            ["code", "dt", "period"],
            ["open", "high", "low", "close", "volume", "amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_adjust(
    code: str, start: str, end: str, provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "adjust")
    factors = provider.get_adjust_factors(code, start, end)
    now = _now()
    rows = [
        {
            "code": f.code,
            "ex_date": f.ex_date,
            "adjust_factor": to_decimal(f.adjust_factor, 6),
            "fore_adjust_factor": to_decimal(f.fore_adjust_factor, 6),
            "back_adjust_factor": to_decimal(f.back_adjust_factor, 6),
            "source": provider.name,
            "fetched_at": now,
        }
        for f in factors
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            AdjustFactor,
            rows,
            ["code", "ex_date"],
            ["adjust_factor", "fore_adjust_factor", "back_adjust_factor", "source", "fetched_at"],
        )
        session.commit()
    return n


def fetch_quotes(
    codes: list[str] | None = None, provider_name: str | None = None
) -> list[QuoteDTO]:
    provider = _resolve(provider_name, "realtime")
    return provider.get_realtime_quotes(codes)


def ingest_capital_flow(code: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "capital_flow")
    items = provider.get_capital_flow(code)
    now = _now()
    rows = [
        {
            "code": r.code,
            "trade_date": r.trade_date,
            "main_net": to_decimal(r.main_net),
            "main_net_ratio": to_decimal(r.main_net_ratio),
            "super_large_net": to_decimal(r.super_large_net),
            "large_net": to_decimal(r.large_net),
            "medium_net": to_decimal(r.medium_net),
            "small_net": to_decimal(r.small_net),
            "source": provider.name,
            "fetched_at": now,
        }
        for r in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            CapitalFlow,
            rows,
            ["code", "trade_date"],
            ["main_net", "main_net_ratio", "super_large_net", "large_net", "medium_net", "small_net", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_financials(code: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "financials")
    items = provider.get_financials(code)
    now = _now()
    rows = [
        {
            "code": r.code,
            "report_date": r.report_date,
            "eps": to_decimal(r.eps),
            "bps": to_decimal(r.bps),
            "roe": to_decimal(r.roe),
            "revenue": to_decimal(r.revenue),
            "net_profit": to_decimal(r.net_profit),
            "gross_margin": to_decimal(r.gross_margin),
            "source": provider.name,
            "fetched_at": now,
        }
        for r in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            FinancialSummary,
            rows,
            ["code", "report_date"],
            ["eps", "bps", "roe", "revenue", "net_profit", "gross_margin", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_dragon_tiger(start: str, end: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "dragon_tiger")
    items = provider.get_dragon_tiger(start, end)
    now = _now()
    rows = [
        {
            "code": r.code,
            "trade_date": r.trade_date,
            "reason": r.reason or "—",
            "name": r.name,
            "net_buy": to_decimal(r.net_buy),
            "buy_amount": to_decimal(r.buy_amount),
            "sell_amount": to_decimal(r.sell_amount),
            "source": provider.name,
            "fetched_at": now,
        }
        for r in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            DragonTiger,
            rows,
            ["code", "trade_date", "reason"],
            ["name", "net_buy", "buy_amount", "sell_amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_news(code: str, limit: int = 30, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "news")
    items = provider.get_news(code, limit)
    now = _now()
    rows = []
    for r in items:
        key = (r.url or r.title or "").encode("utf-8")
        if not key:
            continue
        rows.append(
            {
                "id": hashlib.sha1(key).hexdigest(),
                "code": r.code,
                "title": r.title,
                "url": r.url,
                "source_name": r.source_name,
                "published_at": r.published_at,
                "summary": r.summary,
                "source": provider.name,
                "fetched_at": now,
            }
        )
    with SessionLocal() as session:
        n = _upsert(
            session,
            NewsItem,
            rows,
            ["id"],
            ["code", "title", "url", "source_name", "published_at", "summary", "source", "fetched_at"],
        )
        session.commit()
    return n
