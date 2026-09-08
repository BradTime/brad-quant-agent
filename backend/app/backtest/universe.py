"""Point-in-time daily universe eligibility without snapshot leakage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.backtest.data import Bar


@dataclass(frozen=True)
class PITUniverseFilters:
    min_listing_sessions: int = 120
    amount_lookback: int = 20
    min_average_amount: float = 50_000_000.0
    require_status_coverage: bool = True
    require_audited_data: bool = True


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reasons: tuple[str, ...]
    average_amount: float | None = None
    listing_sessions: int | None = None


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _listing_sessions(list_date: date, as_of: date) -> int:
    if list_date > as_of:
        return 0
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XSHG")
        return len(
            calendar.sessions_in_range(
                list_date.isoformat(),
                as_of.isoformat(),
            )
        )
    except (ImportError, ValueError, RuntimeError):
        return 0


def expected_session_dates(start: date, end: date) -> tuple[str, ...]:
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar("XSHG")
        return tuple(
            timestamp.date().isoformat()
            for timestamp in calendar.sessions_in_range(
                start.isoformat(),
                end.isoformat(),
            )
        )
    except (ImportError, ValueError, RuntimeError) as exc:
        raise RuntimeError("无法加载 XSHG 交易日历，PIT 过滤已拒绝") from exc


def eligible_asof(
    *,
    as_of: date,
    bars: list[Bar],
    list_date: date | None,
    data_quality: str,
    filters: PITUniverseFilters = PITUniverseFilters(),
) -> Eligibility:
    visible = [bar for bar in bars if _day(bar.date) <= as_of]
    today = next(
        (bar for bar in reversed(visible) if _day(bar.date) == as_of),
        None,
    )
    reasons: list[str] = []
    sessions: int | None = None
    average_amount: float | None = None
    if list_date is None:
        reasons.append("missing_list_date")
    else:
        sessions = _listing_sessions(list_date, as_of)
        if sessions < filters.min_listing_sessions:
            reasons.append("young_listing")
    if filters.require_audited_data and data_quality != "full":
        reasons.append("bad_data")
    if today is None or today.volume is None or today.volume <= 0:
        reasons.append("suspended")
    elif today.status_type in {"st", "star_st"}:
        reasons.append("st")
    elif today.status_type in {"suspended", "halted"}:
        reasons.append("suspended")
    elif today.status_type in {"delisting", "delisted"}:
        reasons.append("delisting")
    elif filters.require_status_coverage and today.status_type is None:
        reasons.append("pit_status_missing")
    liquidity_window = visible[-filters.amount_lookback :]
    amounts = [
        float(bar.amount)
        for bar in liquidity_window
        if bar.amount is not None and float(bar.amount) > 0
    ]
    if len(amounts) != filters.amount_lookback:
        reasons.append("liquidity_history_missing")
    else:
        average_amount = sum(amounts) / len(amounts)
        if average_amount < filters.min_average_amount:
            reasons.append("low_liquidity")
    return Eligibility(
        eligible=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        average_amount=average_amount,
        listing_sessions=sessions,
    )
