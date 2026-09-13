"""Materialize and query PIT full-A daily universe membership."""

from __future__ import annotations

import bisect
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select

from app.backtest.data import Bar
from app.backtest.universe import PITUniverseFilters, eligible_asof
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.market import (
    DailyBar,
    Instrument,
    InstrumentStatusHistory,
    InstrumentSuspensionDaily,
)
from app.models.universe import UniverseMembershipDaily, UniverseSnapshotDaily

RULES_VERSION = "pit-universe-v4"
DEFAULT_FILTERS = PITUniverseFilters()
FILTERS_SHA256 = hashlib.sha256(
    json.dumps(
        asdict(DEFAULT_FILTERS),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


def update_membership_digest(
    digest,
    *,
    code: str,
    eligible: bool,
    reasons: tuple[str, ...],
    average_amount: float | None,
    listing_sessions: int | None,
) -> None:
    digest.update(
        json.dumps(
            {
                "code": code,
                "eligible": eligible,
                "reasons": list(reasons),
                "averageAmount": (
                    round(float(average_amount), 4)
                    if average_amount is not None
                    else None
                ),
                "listingSessions": listing_sessions,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


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
    filters = DEFAULT_FILTERS
    warmup_start = as_of - timedelta(days=max(filters.amount_lookback * 4, 180))
    with SessionLocal.begin() as session:
        existing = session.get(
            UniverseSnapshotDaily,
            {"trade_date": as_of, "rules_version": RULES_VERSION},
        )
        if existing:
            return {
                "date": as_of.isoformat(),
                "rulesVersion": RULES_VERSION,
                "total": existing.member_count,
                "eligible": existing.eligible_count,
                "excluded": existing.member_count - existing.eligible_count,
                "advancing": existing.advancing_count,
                "declining": existing.declining_count,
                "reasons": {},
                "membershipSha256": existing.membership_sha256,
                "reused": True,
            }
        instruments = session.execute(
            select(Instrument).where(
                Instrument.security_type == "stock",
                Instrument.exchange.in_(("SH", "SZ", "BJ")),
                Instrument.list_date.is_not(None),
                Instrument.list_date <= as_of,
            ).order_by(Instrument.code)
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
                ).order_by(
                    InstrumentStatusHistory.code,
                    InstrumentStatusHistory.start_date,
                )
            ).scalars().all()
        else:
            statuses = []
        suspended_codes = set(
            session.execute(
                select(InstrumentSuspensionDaily.code).where(
                    InstrumentSuspensionDaily.code.in_(codes),
                    InstrumentSuspensionDaily.trade_date == as_of,
                )
            ).scalars()
        ) if codes else set()
        status_by_code = {row.code: row.status_type for row in statuses}
        status_by_code.update(
            {code: "suspended" for code in suspended_codes}
        )
        reason_counts: dict[str, int] = defaultdict(int)
        eligible_count = 0
        advancing_count = 0
        declining_count = 0
        digest = hashlib.sha256()
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
            if eligibility.eligible and len(source_rows) >= 2:
                previous_close = source_rows[-2].close
                current_close = source_rows[-1].close
                if previous_close is not None and current_close is not None:
                    if current_close > previous_close:
                        advancing_count += 1
                    elif current_close < previous_close:
                        declining_count += 1
            for reason in eligibility.reasons:
                reason_counts[reason] += 1
            update_membership_digest(
                digest,
                code=instrument.code,
                eligible=eligibility.eligible,
                reasons=eligibility.reasons,
                average_amount=eligibility.average_amount,
                listing_sessions=eligibility.listing_sessions,
            )
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
        session.add(
            UniverseSnapshotDaily(
                trade_date=as_of,
                rules_version=RULES_VERSION,
                member_count=len(instruments),
                eligible_count=eligible_count,
                advancing_count=advancing_count,
                declining_count=declining_count,
                filters_sha256=FILTERS_SHA256,
                membership_sha256=digest.hexdigest(),
            )
        )
    return {
        "date": as_of.isoformat(),
        "rulesVersion": RULES_VERSION,
        "total": len(instruments),
        "eligible": eligible_count,
        "excluded": len(instruments) - eligible_count,
        "advancing": advancing_count,
        "declining": declining_count,
        "reasons": dict(sorted(reason_counts.items())),
        "membershipSha256": digest.hexdigest(),
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


def build_range(
    start: date,
    end: date,
    *,
    chunk_sessions: int | None = None,
) -> dict[str, Any]:
    if start > end:
        raise ValueError("start 不能晚于 end")
    from app.backtest.universe import expected_session_dates
    from app.core.config import settings

    session_dates = [
        date.fromisoformat(value)
        for value in expected_session_dates(start, end)
    ]
    if not session_dates:
        raise ValueError("请求区间没有 XSHG 交易日")
    chunk_size = chunk_sessions or settings.full_a_backtest_chunk_sessions
    with SessionLocal() as session:
        existing_dates = set(
            session.execute(
                select(UniverseSnapshotDaily.trade_date).where(
                    UniverseSnapshotDaily.trade_date.in_(session_dates),
                    UniverseSnapshotDaily.rules_version == RULES_VERSION,
                )
            ).scalars()
        )
        instruments = session.execute(
            select(Instrument).where(
                Instrument.security_type == "stock",
                Instrument.exchange.in_(("SH", "SZ", "BJ")),
                Instrument.list_date.is_not(None),
                Instrument.list_date <= end,
            ).order_by(Instrument.code)
        ).scalars().all()
    pending_dates = [day for day in session_dates if day not in existing_dates]
    if not pending_dates:
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "rulesVersion": RULES_VERSION,
            "dates": len(session_dates),
            "createdDates": 0,
            "reusedDates": len(session_dates),
        }
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XSHG")
    earliest_list_date = min(
        instrument.list_date for instrument in instruments
        if instrument.list_date is not None
    )
    calendar_start = calendar.first_session.date()
    history_start = max(earliest_list_date, calendar_start)
    all_market_dates = [
        timestamp.date()
        for timestamp in calendar.sessions_in_range(
            history_start.isoformat(),
            end.isoformat(),
        )
    ]
    filters = DEFAULT_FILTERS
    created = 0
    for offset in range(0, len(pending_dates), chunk_size):
        date_chunk = pending_dates[offset : offset + chunk_size]
        first_index = bisect.bisect_left(all_market_dates, date_chunk[0])
        warmup_start = all_market_dates[
            max(0, first_index - filters.amount_lookback)
        ]
        with SessionLocal.begin() as session:
            daily_rows = session.execute(
                select(DailyBar)
                .where(
                    DailyBar.trade_date >= warmup_start,
                    DailyBar.trade_date <= date_chunk[-1],
                )
                .order_by(DailyBar.code, DailyBar.trade_date)
            ).scalars().all()
            statuses = session.execute(
                select(InstrumentStatusHistory)
                .where(
                    InstrumentStatusHistory.start_date <= date_chunk[-1],
                    or_(
                        InstrumentStatusHistory.end_date.is_(None),
                        InstrumentStatusHistory.end_date >= date_chunk[0],
                    ),
                )
                .order_by(
                    InstrumentStatusHistory.code,
                    InstrumentStatusHistory.start_date,
                )
            ).scalars().all()
            suspension_keys = set(
                session.execute(
                    select(
                        InstrumentSuspensionDaily.code,
                        InstrumentSuspensionDaily.trade_date,
                    ).where(
                        InstrumentSuspensionDaily.trade_date.in_(
                            date_chunk
                        )
                    )
                ).all()
            )
            rows_by_code: dict[str, list[DailyBar]] = defaultdict(list)
            row_dates_by_code: dict[str, list[date]] = defaultdict(list)
            for row in daily_rows:
                rows_by_code[row.code].append(row)
                row_dates_by_code[row.code].append(row.trade_date)
            status_by_code: dict[
                str, list[InstrumentStatusHistory]
            ] = defaultdict(list)
            status_starts: dict[str, list[date]] = defaultdict(list)
            for row in statuses:
                status_by_code[row.code].append(row)
                status_starts[row.code].append(row.start_date)
            inserts: list[UniverseMembershipDaily] = []
            digests = {
                trade_date: hashlib.sha256()
                for trade_date in date_chunk
            }
            member_counts = {trade_date: 0 for trade_date in date_chunk}
            eligible_counts = {trade_date: 0 for trade_date in date_chunk}
            advancing_counts = {trade_date: 0 for trade_date in date_chunk}
            declining_counts = {trade_date: 0 for trade_date in date_chunk}
            for trade_date in date_chunk:
                market_index = bisect.bisect_right(
                    all_market_dates, trade_date
                )
                for instrument in instruments:
                    if (
                        instrument.list_date is None
                        or instrument.list_date > trade_date
                    ):
                        continue
                    code_rows = rows_by_code.get(instrument.code, [])
                    row_end = bisect.bisect_right(
                        row_dates_by_code.get(instrument.code, []),
                        trade_date,
                    )
                    source_rows = code_rows[
                        max(0, row_end - filters.amount_lookback) : row_end
                    ]
                    status = None
                    starts = status_starts.get(instrument.code, [])
                    status_index = bisect.bisect_right(starts, trade_date) - 1
                    if status_index >= 0:
                        candidate = status_by_code[instrument.code][
                            status_index
                        ]
                        if (
                            candidate.end_date is None
                            or trade_date <= candidate.end_date
                        ):
                            status = candidate.status_type
                    if (
                        instrument.code,
                        trade_date,
                    ) in suspension_keys:
                        status = "suspended"
                    bars = [
                        Bar(
                            code=row.code,
                            date=row.trade_date,
                            open=float(row.open or 0),
                            high=float(row.high or 0),
                            low=float(row.low or 0),
                            close=float(row.close or 0),
                            volume=row.volume,
                            amount=(
                                float(row.amount)
                                if row.amount is not None
                                else None
                            ),
                            status_type=(
                                status
                                if row.trade_date == trade_date
                                else None
                            ),
                        )
                        for row in source_rows
                    ]
                    list_index = bisect.bisect_left(
                        all_market_dates, instrument.list_date
                    )
                    listing_sessions = market_index - list_index
                    eligibility = eligible_asof(
                        as_of=trade_date,
                        bars=bars,
                        list_date=instrument.list_date,
                        data_quality=(
                            "full"
                            if _complete_daily_rows(source_rows)
                            else "bad_data"
                        ),
                        filters=filters,
                        listing_sessions=listing_sessions,
                    )
                    member_counts[trade_date] += 1
                    eligible_counts[trade_date] += int(
                        eligibility.eligible
                    )
                    if eligibility.eligible and len(source_rows) >= 2:
                        previous_close = source_rows[-2].close
                        current_close = source_rows[-1].close
                        if (
                            previous_close is not None
                            and current_close is not None
                        ):
                            if current_close > previous_close:
                                advancing_counts[trade_date] += 1
                            elif current_close < previous_close:
                                declining_counts[trade_date] += 1
                    update_membership_digest(
                        digests[trade_date],
                        code=instrument.code,
                        eligible=eligibility.eligible,
                        reasons=eligibility.reasons,
                        average_amount=eligibility.average_amount,
                        listing_sessions=eligibility.listing_sessions,
                    )
                    inserts.append(
                        UniverseMembershipDaily(
                            code=instrument.code,
                            trade_date=trade_date,
                            eligible=eligibility.eligible,
                            reasons_json=dump_envelope(
                                list(eligibility.reasons)
                            ),
                            average_amount=eligibility.average_amount,
                            listing_sessions=eligibility.listing_sessions,
                            rules_version=RULES_VERSION,
                        )
                    )
            session.add_all(inserts)
            session.add_all(
                [
                    UniverseSnapshotDaily(
                        trade_date=trade_date,
                        rules_version=RULES_VERSION,
                        member_count=member_counts[trade_date],
                        eligible_count=eligible_counts[trade_date],
                        advancing_count=advancing_counts[trade_date],
                        declining_count=declining_counts[trade_date],
                        filters_sha256=FILTERS_SHA256,
                        membership_sha256=digests[
                            trade_date
                        ].hexdigest(),
                    )
                    for trade_date in date_chunk
                ]
            )
        created += len(date_chunk)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rulesVersion": RULES_VERSION,
        "dates": len(session_dates),
        "createdDates": created,
        "reusedDates": len(session_dates) - created,
    }


def eligible_map(
    codes: list[str], start: date, end: date
) -> dict[str, tuple[str, ...]]:
    with SessionLocal() as session:
        snapshots = list(
            session.execute(
                select(UniverseSnapshotDaily)
                .where(
                    UniverseSnapshotDaily.trade_date >= start,
                    UniverseSnapshotDaily.trade_date <= end,
                    UniverseSnapshotDaily.rules_version == RULES_VERSION,
                )
                .order_by(UniverseSnapshotDaily.trade_date)
            ).scalars().all()
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
    if any(snapshot.filters_sha256 != FILTERS_SHA256 for snapshot in snapshots):
        raise ValueError("PIT 股票池过滤规则指纹不匹配")
    result: dict[str, list[str]] = {
        snapshot.trade_date.isoformat(): [] for snapshot in snapshots
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
