"""Ingestion: pull from a provider and upsert into Postgres.

Upserts use PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` so re-runs are
idempotent. Realtime quotes are not persisted here (transient); ``fetch_quotes``
just returns them for connectivity checks / API serving.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.numeric import to_decimal, to_int
from app.db.session import SessionLocal
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
    stmt = pg_insert(model).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={c: getattr(stmt.excluded, c) for c in update_cols},
    )
    session.execute(stmt)
    return len(rows)


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
