"""Chunked, cancel-aware full-A cross-sectional daily backtest executor."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import aliased

from app.backtest.base import BacktestConfig
from app.backtest.broker import Broker
from app.backtest.context import Context
from app.backtest.data import Bar
from app.backtest.metrics import compute_metrics
from app.backtest.strategies import get_strategy
from app.core.config import settings
from app.core.json_payload import load_envelope
from app.core.ohlc import InvalidOHLCError, validate_ohlc
from app.db.session import SessionLocal
from app.models.market import AdjustFactor, DailyBar, Instrument
from app.models.universe import (
    UniverseMembershipDaily,
    UniverseSnapshotDaily,
)
from app.services import trading_rules
from app.services.universe_membership import (
    FILTERS_SHA256,
    RULES_VERSION,
    update_membership_digest,
)

_SUPPORTED = {"xs_momentum", "composite_mf"}
_FIELDS = ("close", "amount", "volume")
_CancelCheck = Callable[[], bool]
_Progress = Callable[[int, int], None]


def _warmup_size(strategy_type: str, params: dict[str, Any]) -> int:
    if strategy_type in _SUPPORTED:
        return int(params.get("lookback", 60)) + 1
    raise ValueError("全 A 分块回测仅支持截面动量或价格量能多因子")


def _session_window(start: date, end: date, warmup: int) -> tuple[list[date], list[date]]:
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XSHG")
    prior_start = start - timedelta(days=max(warmup * 3, 370))
    all_sessions = [
        timestamp.date()
        for timestamp in calendar.sessions_in_range(
            prior_start.isoformat(),
            end.isoformat(),
        )
    ]
    run_dates = [day for day in all_sessions if start <= day <= end]
    prior = [day for day in all_sessions if day < start][-warmup:]
    if not run_dates:
        raise ValueError("请求区间没有 XSHG 交易日")
    return [*prior, *run_dates], run_dates


def _chunks(values: list[date], size: int) -> Iterator[list[date]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _load_instrument_dates() -> dict[str, date | None]:
    with SessionLocal() as session:
        return dict(
            session.execute(
                select(Instrument.code, Instrument.list_date).where(
                    Instrument.security_type == "stock",
                    Instrument.exchange.in_(("SH", "SZ", "BJ")),
                )
            ).all()
        )


def _load_adjustments(
    codes: set[str], start: date, end: date
) -> tuple[dict[str, list[date]], dict[str, list[float]]]:
    dates: dict[str, list[date]] = defaultdict(list)
    values: dict[str, list[float]] = defaultdict(list)
    if not codes:
        return dates, values
    prior = aliased(AdjustFactor)
    latest_prior = (
        select(func.max(prior.ex_date))
        .where(
            prior.code == AdjustFactor.code,
            prior.ex_date < start,
        )
        .correlate(AdjustFactor)
        .scalar_subquery()
    )
    with SessionLocal() as session:
        rows = session.execute(
            select(
                AdjustFactor.code,
                AdjustFactor.ex_date,
                AdjustFactor.back_adjust_factor,
            )
            .where(
                AdjustFactor.code.in_(codes),
                or_(
                    AdjustFactor.ex_date.between(start, end),
                    AdjustFactor.ex_date == latest_prior,
                ),
            )
            .order_by(AdjustFactor.code, AdjustFactor.ex_date)
        ).all()
    invalid_codes: set[str] = set()
    for code, ex_date, back_factor in rows:
        if back_factor is None:
            invalid_codes.add(code)
            continue
        value = float(back_factor)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{code} {ex_date} 后复权因子无效")
        dates[code].append(ex_date)
        values[code].append(value)
    missing_codes = codes - set(dates)
    invalid_codes.update(missing_codes)
    if invalid_codes:
        sample = sorted(invalid_codes)[0]
        raise ValueError(
            "全 A 回测要求完整后复权因子；"
            f"{sample} 等 {len(invalid_codes)} 个标的缺失"
        )
    return dates, values


def _factor_at(
    code: str,
    on: date,
    factor_dates: dict[str, list[date]],
    factor_values: dict[str, list[float]],
) -> float:
    dates = factor_dates.get(code, [])
    if not dates:
        raise ValueError(f"{code} 缺少后复权因子")
    index = bisect.bisect_right(dates, on) - 1
    return factor_values[code][index] if index >= 0 else factor_values[code][0]


def _load_membership(
    dates: list[date],
) -> tuple[
    dict[date, set[str]],
    dict[date, dict[str, tuple[str, ...]]],
    dict[date, str],
]:
    with SessionLocal() as session:
        snapshots = list(
            session.execute(
                select(UniverseSnapshotDaily).where(
                    UniverseSnapshotDaily.trade_date.in_(dates),
                    UniverseSnapshotDaily.rules_version == RULES_VERSION,
                )
            ).scalars().all()
        )
        rows = session.execute(
            select(
                UniverseMembershipDaily.trade_date,
                UniverseMembershipDaily.code,
                UniverseMembershipDaily.eligible,
                UniverseMembershipDaily.reasons_json,
                UniverseMembershipDaily.average_amount,
                UniverseMembershipDaily.listing_sessions,
            )
            .where(
                UniverseMembershipDaily.trade_date.in_(dates),
                UniverseMembershipDaily.rules_version == RULES_VERSION,
            )
            .order_by(
                UniverseMembershipDaily.trade_date,
                UniverseMembershipDaily.code,
            )
        ).all()
    eligible: dict[date, set[str]] = {day: set() for day in dates}
    reasons: dict[date, dict[str, tuple[str, ...]]] = {
        day: {} for day in dates
    }
    snapshot_by_date = {row.trade_date: row for row in snapshots}
    digests = {day: hashlib.sha256() for day in dates}
    counts = {day: 0 for day in dates}
    eligible_counts = {day: 0 for day in dates}
    for (
        trade_date,
        code,
        is_eligible,
        raw_reasons,
        average_amount,
        listing_sessions,
    ) in rows:
        counts[trade_date] += 1
        eligible_counts[trade_date] += int(is_eligible)
        payload = load_envelope(
            raw_reasons,
            expect="list",
            field="reasons_json",
        )
        reason_values = tuple(str(item) for item in payload)
        update_membership_digest(
            digests[trade_date],
            code=code,
            eligible=is_eligible,
            reasons=reason_values,
            average_amount=(
                float(average_amount)
                if average_amount is not None
                else None
            ),
            listing_sessions=listing_sessions,
        )
        if is_eligible:
            eligible[trade_date].add(code)
        else:
            reasons[trade_date][code] = reason_values
    missing = [day for day in dates if day not in snapshot_by_date]
    if missing:
        raise ValueError(
            "PIT 全 A 股票池覆盖不完整，缺少 "
            f"{missing[0].isoformat()} 等 {len(missing)} 日"
        )
    snapshot_hashes: dict[date, str] = {}
    for day in dates:
        snapshot = snapshot_by_date[day]
        digest = digests[day].hexdigest()
        if (
            snapshot.filters_sha256 != FILTERS_SHA256
            or snapshot.member_count != counts[day]
            or snapshot.eligible_count != eligible_counts[day]
            or snapshot.membership_sha256 != digest
        ):
            raise ValueError(f"{day.isoformat()} PIT 股票池完整性校验失败")
        snapshot_hashes[day] = digest
    return eligible, reasons, snapshot_hashes


def _membership_codes(run_dates: list[date]) -> set[str]:
    with SessionLocal() as session:
        snapshots = list(
            session.execute(
                select(UniverseSnapshotDaily).where(
                    UniverseSnapshotDaily.trade_date.in_(run_dates),
                    UniverseSnapshotDaily.rules_version == RULES_VERSION,
                )
            ).scalars().all()
        )
        codes = set(
            session.execute(
                select(distinct(UniverseMembershipDaily.code)).where(
                    UniverseMembershipDaily.trade_date.in_(run_dates),
                    UniverseMembershipDaily.rules_version == RULES_VERSION,
                    UniverseMembershipDaily.eligible.is_(True),
                )
            ).scalars()
        )
    snapshot_by_date = {row.trade_date: row for row in snapshots}
    missing = [day for day in run_dates if day not in snapshot_by_date]
    if missing:
        raise ValueError(
            "PIT 全 A 股票池覆盖不完整，缺少 "
            f"{missing[0].isoformat()} 等 {len(missing)} 日"
        )
    if any(row.filters_sha256 != FILTERS_SHA256 for row in snapshots):
        raise ValueError("PIT 全 A 股票池过滤规则指纹不匹配")
    if not codes:
        raise ValueError("请求区间的 PIT 全 A 股票池没有合格标的")
    return codes


def _load_bar_rows(dates: list[date], codes: set[str]) -> list[DailyBar]:
    if not dates or not codes:
        return []
    with SessionLocal() as session:
        return list(
            session.execute(
                select(DailyBar)
                .where(
                    DailyBar.code.in_(codes),
                    DailyBar.trade_date.in_(dates),
                )
                .order_by(DailyBar.trade_date, DailyBar.code)
                .execution_options(yield_per=10_000)
            ).scalars()
        )


def run_chunked(
    config: BacktestConfig,
    *,
    cancel_check: _CancelCheck | None = None,
    on_progress: _Progress | None = None,
) -> dict[str, Any]:
    if config.strategy_type not in _SUPPORTED:
        raise ValueError("全 A 分块回测仅支持截面动量或价格量能多因子")
    warmup = _warmup_size(config.strategy_type, config.params)
    all_dates, run_dates = _session_window(
        date.fromisoformat(config.start[:10]),
        date.fromisoformat(config.end[:10]),
        warmup,
    )
    all_codes = _membership_codes(run_dates)
    list_dates = _load_instrument_dates()
    factor_dates, factor_values = _load_adjustments(
        all_codes,
        all_dates[0],
        run_dates[-1],
    )
    base_factors: dict[str, float] = {}
    histories: dict[str, dict[str, deque[float]]] = defaultdict(
        lambda: {
            field: deque(maxlen=warmup)
            for field in _FIELDS
        }
    )
    broker = Broker(
        config.initial_capital,
        config.slippage,
        config.max_participation,
    )

    def history_fn(code: str, field: str, n: int, _as_of) -> list[float]:
        return list(histories.get(code, {}).get(field, ())) [-n:]

    context = Context(broker, config.params, history_fn, universe=[])
    strategy = get_strategy(config.strategy_type)
    strategy.initialize(context)
    equity_curve: list[dict[str, Any]] = []
    data_digest = hashlib.sha256()
    universe_digest = hashlib.sha256()
    last_closes: dict[str, float] = {}
    processed = 0
    run_date_set = set(run_dates)
    minimum_eligible: int | None = None
    maximum_eligible = 0
    chunk_size = settings.full_a_backtest_chunk_sessions
    for date_chunk in _chunks(all_dates, chunk_size):
        if cancel_check and cancel_check():
            return {"cancelled": True, "progressDone": processed, "progressTotal": len(run_dates)}
        if on_progress:
            on_progress(processed, len(run_dates))
        rows_by_date: dict[date, list[DailyBar]] = defaultdict(list)
        for row in _load_bar_rows(date_chunk, all_codes):
            rows_by_date[row.trade_date].append(row)
        run_chunk_dates = [
            day for day in date_chunk if day in run_date_set
        ]
        if run_chunk_dates:
            (
                eligible_by_date,
                reasons_by_date,
                snapshot_hashes,
            ) = _load_membership(run_chunk_dates)
        else:
            eligible_by_date, reasons_by_date, snapshot_hashes = {}, {}, {}
        for current_date in date_chunk:
            if cancel_check and cancel_check():
                return {
                    "cancelled": True,
                    "progressDone": processed,
                    "progressTotal": len(run_dates),
                }
            bars_today: dict[str, Bar] = {}
            reason_map = reasons_by_date.get(current_date, {})
            for row in rows_by_date.get(current_date, []):
                try:
                    checked = validate_ohlc(
                        open_value=row.open,
                        high_value=row.high,
                        low_value=row.low,
                        close_value=row.close,
                        volume=row.volume,
                        amount=row.amount,
                        code=row.code,
                        bar_time=row.trade_date,
                    )
                except InvalidOHLCError as exc:
                    if row.code in eligible_by_date.get(current_date, set()):
                        raise ValueError(
                            f"{row.code} {current_date} OHLC 不可信"
                        ) from exc
                    continue
                factor = _factor_at(
                    row.code, current_date, factor_dates, factor_values
                )
                base = base_factors.setdefault(row.code, factor)
                ratio = factor / base if base > 0 else 1.0
                status_reasons = reason_map.get(row.code, ())
                adjusted = Bar(
                    code=row.code,
                    date=current_date,
                    open=round(float(checked.open) * ratio, 4),
                    high=round(float(checked.high) * ratio, 4),
                    low=round(float(checked.low) * ratio, 4),
                    close=round(float(checked.close) * ratio, 4),
                    volume=(
                        int(checked.volume)
                        if checked.volume is not None
                        else None
                    ),
                    amount=(
                        float(checked.amount)
                        if checked.amount is not None
                        else None
                    ),
                    previous_close=last_closes.get(row.code),
                    limit_ratio=trading_rules.price_limit_ratio(
                        row.code,
                        trade_date=current_date,
                        list_date=list_dates.get(row.code),
                        is_st=("st" in status_reasons),
                    ),
                    status_type=(
                        "st" if "st" in status_reasons else "normal"
                    ),
                )
                bars_today[row.code] = adjusted
                last_closes[row.code] = adjusted.close
                histories[row.code]["close"].append(adjusted.close)
                if adjusted.amount is not None:
                    histories[row.code]["amount"].append(adjusted.amount)
                if adjusted.volume is not None:
                    histories[row.code]["volume"].append(float(adjusted.volume))
                data_digest.update(
                    json.dumps(
                        {
                            "date": current_date.isoformat(),
                            "code": row.code,
                            "open": adjusted.open,
                            "high": adjusted.high,
                            "low": adjusted.low,
                            "close": adjusted.close,
                            "volume": adjusted.volume,
                            "amount": adjusted.amount,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                )
            if current_date not in run_date_set:
                continue
            eligible = eligible_by_date[current_date]
            eligible_count = len(eligible)
            minimum_eligible = (
                eligible_count
                if minimum_eligible is None
                else min(minimum_eligible, eligible_count)
            )
            maximum_eligible = max(maximum_eligible, eligible_count)
            eligible_bars = {
                code: bars_today[code]
                for code in sorted(eligible)
                if code in bars_today
            }
            missing_eligible = eligible - set(eligible_bars)
            if missing_eligible:
                raise ValueError(
                    f"{current_date} 有 {len(missing_eligible)} 个合格标的缺少可信日线"
                )
            if processed == 0:
                for code, bar in bars_today.items():
                    if bar.previous_close is not None:
                        broker.seed_previous_close(
                            code, bar.previous_close
                        )
            broker.settle_t1(current_date)
            broker.execute_open(bars_today, current_date)
            context._set_date(current_date)
            context.set_universe(sorted(eligible))
            broker.set_signal_bars(bars_today)
            for code, position in broker.positions.items():
                if position.qty > 0 and code not in eligible:
                    context.order_target_percent(code, 0.0)
            strategy.handle_bar(context, eligible_bars)
            equity = round(broker.mark_to_market(bars_today), 2)
            equity_curve.append(
                {
                    "date": current_date.isoformat(),
                    "equity": equity,
                    "cash": round(broker.cash, 2),
                    "marketValue": round(equity - broker.cash, 2),
                }
            )
            eligible_codes = sorted(eligible)
            universe_digest.update(
                json.dumps(
                    [
                        current_date.isoformat(),
                        snapshot_hashes[current_date],
                        eligible_codes,
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            processed += 1
            if on_progress:
                on_progress(processed, len(run_dates))
    computed = compute_metrics(
        equity_curve,
        broker.fills,
        config.initial_capital,
    )
    from app.backtest import runner

    benchmark_bars, benchmark_quality = runner.load_benchmark_with_quality(
        config.start,
        config.end,
    )
    if benchmark_quality in {"invalid_ohlc", "partial_ingestion"}:
        raise ValueError("沪深300基准数据不可信，已拒绝回测")
    benchmark_bars = [
        bar
        for bar in benchmark_bars
        if run_dates[0] <= bar.date <= run_dates[-1]
    ]
    if not benchmark_bars:
        raise ValueError("沪深300基准数据缺失，已拒绝全 A 回测")
    benchmark_dates = {bar.date for bar in benchmark_bars}
    missing_benchmark_dates = [
        day for day in run_dates if day not in benchmark_dates
    ]
    if missing_benchmark_dates:
        raise ValueError(
            "沪深300基准日期覆盖不完整，缺少 "
            f"{missing_benchmark_dates[0].isoformat()} 等 "
            f"{len(missing_benchmark_dates)} 日"
        )
    benchmark_digest = hashlib.sha256(
        json.dumps(
            [
                {
                    "date": bar.date.isoformat(),
                    "close": bar.close,
                }
                for bar in benchmark_bars
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    runner._attach_benchmark(  # noqa: SLF001
        computed,
        {},
        config.start,
        config.end,
        benchmark_bars,
    )
    computed.update(
        {
            "engine": "native-full-a-chunked",
            "dataQuality": {
                "dailyBarsSha256": data_digest.hexdigest(),
                "benchmarkSha256": benchmark_digest,
                "benchmark": benchmark_quality,
            },
            "executionQuality": {
                "slippage": broker.slippage,
                "maxParticipation": broker.max_participation,
                "volumeCappedFills": broker.volume_capped_fills,
                "volumeMissingRejections": broker.volume_missing_rejections,
            },
            "universeQuality": {
                "mode": "full_a_pit",
                "rulesVersion": RULES_VERSION,
                "membershipSha256": universe_digest.hexdigest(),
                "materializedDates": len(run_dates),
                "minEligible": minimum_eligible or 0,
                "maxEligible": maximum_eligible,
            },
            "actualRange": {
                "start": run_dates[0].isoformat(),
                "end": run_dates[-1].isoformat(),
            },
            "ruleQuality": {
                "historicalST": "materialized-pit",
                "priceLimit": "board/date rules + materialized PIT status",
            },
        }
    )
    return computed
