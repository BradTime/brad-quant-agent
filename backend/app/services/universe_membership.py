"""Materialize and query PIT full-A daily universe membership."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import distinct, func, or_, select

from app.backtest.data import Bar
from app.backtest.universe import PITUniverseFilters, eligible_asof
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.market import DailyBar, Instrument, InstrumentStatusHistory
from app.models.universe import UniverseMembershipDaily

RULES_VERSION = "pit-universe-v1"


def _complete_daily_rows(rows: list[DailyBar]) -> bool:
    return bool(
        rows
        and all(
            value is not None and float(value) > 0
            for row in rows
            for value in (row.open, row.high, row.low, row.close)
        )
    )


def build_for_date(
    as_of: date,
) -> dict[str, Any]:
    filters = PITUniverseFilters()
    warmup_start = as_of - timedelta(days=max(filters.amount_lookback * 4, 180))
    with SessionLocal.begin() as session:
        existing = session.scalar(
            select(func.count())
            .select_from(UniverseMembershipDaily)
            .where(
                UniverseMembershipDaily.trade_date == as_of,
                UniverseMembershipDaily.rules_version == RULES_VERSION,
            )
        )
        if existing:
            eligible_existing = session.scalar(
                select(func.count())
                .select_from(UniverseMembershipDaily)
                .where(
                    UniverseMembershipDaily.trade_date == as_of,
                    UniverseMembershipDaily.rules_version == RULES_VERSION,
                    UniverseMembershipDaily.eligible.is_(True),
                )
            )
            return {
                "date": as_of.isoformat(),
                "rulesVersion": RULES_VERSION,
                "total": int(existing),
                "eligible": int(eligible_existing or 0),
                "excluded": int(existing) - int(eligible_existing or 0),
                "reasons": {},
                "reused": True,
            }
        instruments = session.execute(
            select(Instrument).where(
                Instrument.security_type == "stock",
                Instrument.exchange.in_(("SH", "SZ", "BJ")),
                Instrument.list_date.is_not(None),
                Instrument.list_date <= as_of,
            )
        ).scalars().all()
        codes = [instrument.code for instrument in instruments]
        rows_by_code: dict[str, list[DailyBar]] = defaultdict(list)
        if codes:
            rows = session.execute(
                select(DailyBar)
                .where(
                    DailyBar.code.in_(codes),
                    DailyBar.trade_date >= warmup_start,
                    DailyBar.trade_date <= as_of,
                )
                .order_by(DailyBar.code, DailyBar.trade_date)
            ).scalars().all()
            for row in rows:
                rows_by_code[row.code].append(row)
            statuses = session.execute(
                select(InstrumentStatusHistory).where(
                    InstrumentStatusHistory.code.in_(codes),
                    InstrumentStatusHistory.start_date <= as_of,
                    or_(
                        InstrumentStatusHistory.end_date.is_(None),
                        InstrumentStatusHistory.end_date >= as_of,
                    ),
                )
            ).scalars().all()
        else:
            statuses = []
        status_by_code = {row.code: row.status_type for row in statuses}
        reason_counts: dict[str, int] = defaultdict(int)
        eligible_count = 0
        for instrument in instruments:
            source_rows = rows_by_code.get(instrument.code, [])
            bars = [
                Bar(
                    code=row.code,
                    date=row.trade_date,
                    open=float(row.open or 0),
                    high=float(row.high or 0),
                    low=float(row.low or 0),
                    close=float(row.close or 0),
                    volume=row.volume,
                    amount=float(row.amount) if row.amount is not None else None,
                    status_type=(
                        status_by_code.get(row.code)
                        if row.trade_date == as_of
                        else None
                    ),
                )
                for row in source_rows
            ]
            eligibility = eligible_asof(
                as_of=as_of,
                bars=bars,
                list_date=instrument.list_date,
                data_quality=(
                    "full" if _complete_daily_rows(source_rows) else "bad_data"
                ),
                filters=filters,
            )
            eligible_count += int(eligibility.eligible)
            for reason in eligibility.reasons:
                reason_counts[reason] += 1
            session.add(
                UniverseMembershipDaily(
                    code=instrument.code,
                    trade_date=as_of,
                    eligible=eligibility.eligible,
                    reasons_json=dump_envelope(list(eligibility.reasons)),
                    average_amount=eligibility.average_amount,
                    listing_sessions=eligibility.listing_sessions,
                    rules_version=RULES_VERSION,
                )
            )
    return {
        "date": as_of.isoformat(),
        "rulesVersion": RULES_VERSION,
        "total": len(instruments),
        "eligible": eligible_count,
        "excluded": len(instruments) - eligible_count,
        "reasons": dict(sorted(reason_counts.items())),
        "reused": False,
    }


def eligible_codes(as_of: date) -> list[str]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(UniverseMembershipDaily.code)
                .where(
                    UniverseMembershipDaily.trade_date == as_of,
                    UniverseMembershipDaily.eligible.is_(True),
                    UniverseMembershipDaily.rules_version == RULES_VERSION,
                )
                .order_by(UniverseMembershipDaily.code)
            ).scalars()
        )


def eligible_map(
    codes: list[str], start: date, end: date
) -> dict[str, tuple[str, ...]]:
    with SessionLocal() as session:
        materialized_dates = list(
            session.execute(
                select(distinct(UniverseMembershipDaily.trade_date))
                .where(
                    UniverseMembershipDaily.trade_date >= start,
                    UniverseMembershipDaily.trade_date <= end,
                    UniverseMembershipDaily.rules_version == RULES_VERSION,
                )
                .order_by(UniverseMembershipDaily.trade_date)
            ).scalars()
        )
        rows = session.execute(
            select(
                UniverseMembershipDaily.trade_date,
                UniverseMembershipDaily.code,
                UniverseMembershipDaily.eligible,
            )
            .where(
                UniverseMembershipDaily.code.in_(codes),
                UniverseMembershipDaily.trade_date >= start,
                UniverseMembershipDaily.trade_date <= end,
                UniverseMembershipDaily.rules_version == RULES_VERSION,
            )
            .order_by(
                UniverseMembershipDaily.trade_date,
                UniverseMembershipDaily.code,
            )
        ).all()
    result: dict[str, list[str]] = {
        trade_date.isoformat(): [] for trade_date in materialized_dates
    }
    for trade_date, code, eligible in rows:
        day = trade_date.isoformat()
        result.setdefault(day, [])
        if eligible:
            result[day].append(code)
    return {day: tuple(day_codes) for day, day_codes in result.items()}


def membership(as_of: date, code: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.get(
            UniverseMembershipDaily,
            {
                "code": code,
                "trade_date": as_of,
                "rules_version": RULES_VERSION,
            },
        )
        if row is None:
            return None
        reasons = load_envelope(
            row.reasons_json,
            expect="list",
            field="reasons_json",
        )
        return {
            "code": row.code,
            "date": row.trade_date.isoformat(),
            "eligible": row.eligible,
            "reasons": reasons,
            "averageAmount": (
                float(row.average_amount)
                if row.average_amount is not None
                else None
            ),
            "listingSessions": row.listing_sessions,
            "rulesVersion": row.rules_version,
        }
