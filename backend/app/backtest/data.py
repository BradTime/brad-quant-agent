"""回测数据加载：后复权(HFQ)日线/分钟线 + 交易日历。

回测必须用**后复权**价才能正确跨除权日（后复权不改变历史相对收益，适合回测）。
读 ``daily_bars`` / ``minute_bars``（不复权 OHLC）+ ``adjust_factors``
（后复权因子，按 ex_date 阶梯），输出复权后的 ``Bar`` 序列。缺因子的标的标注
``coverage``（延续"不杜撰、显式标缺口"原则）。
"""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import distinct, func, inspect, or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.ohlc import InvalidOHLCError, validate_ohlc, validate_previous_close
from app.db.session import SessionLocal
from app.models.ingestion import IngestionRun
from app.models.market import AdjustFactor, DailyBar, Instrument, MinuteBar
from app.services import trading_rules as rules


@dataclass
class Bar:
    code: str
    date: date | datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    amount: float | None
    previous_close: float | None = None
    limit_ratio: float | None = None


def trading_calendar(start: str, end: str) -> list[date]:
    """用已落库 ``daily_bars`` 的去重交易日近似交易日历（区间内所有标的的并集）。"""
    with SessionLocal() as session:
        stmt = (
            select(distinct(DailyBar.trade_date))
            .where(DailyBar.trade_date >= start, DailyBar.trade_date <= end)
            .order_by(DailyBar.trade_date)
        )
        return [d for (d,) in session.execute(stmt).all()]


def _is_missing_ingestion_table(exc: Exception) -> bool:
    message = str(exc).lower()
    return "ingestion_runs" in message and (
        "no such table" in message
        or "does not exist" in message
        or "doesn't exist" in message
        or "undefinedtable" in message
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _run_datasets(run: IngestionRun) -> dict[str, dict]:
    try:
        datasets = json.loads(run.datasets_json or "{}")
    except (TypeError, ValueError):
        return {}
    return datasets if isinstance(datasets, dict) else {}


def _required_dataset_keys(frequency: str) -> tuple[str, str]:
    primary = "daily" if frequency == "1d" else f"minute:{frequency.removesuffix('m')}"
    return primary, "adjust"


def _requested_range_covers(
    audit: dict,
    request_start: date,
    request_end: date,
) -> bool:
    requested = audit.get("requested")
    if not isinstance(requested, dict):
        return False
    start = _as_date(requested.get("start"))
    end = _as_date(requested.get("end"))
    return bool(start and end and start <= request_start and end >= request_end)


def _primary_audit_covers(
    audit: dict,
    frequency: str,
    request_start: date,
    request_end: date,
    actual_start: date,
    actual_end: date,
) -> bool:
    if audit.get("success") is not True or audit.get("period") != frequency:
        return False
    if not _requested_range_covers(audit, request_start, request_end):
        return False
    actual = audit.get("actual")
    if not isinstance(actual, dict):
        return False
    persisted_start = _as_date(actual.get("start"))
    persisted_end = _as_date(actual.get("end"))
    return bool(
        persisted_start
        and persisted_end
        and persisted_start <= actual_start
        and persisted_end >= actual_end
    )


def _as_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _comparable_timestamp(value)
    if isinstance(value, str):
        try:
            return _comparable_timestamp(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _dataset_fetched_bounds(
    session: Session,
    code: str,
    dataset: str,
    start: date,
    end: date,
) -> tuple[datetime | None, datetime | None]:
    if dataset == "daily":
        stmt = select(func.min(DailyBar.fetched_at), func.max(DailyBar.fetched_at)).where(
            DailyBar.code == code,
            DailyBar.trade_date >= start,
            DailyBar.trade_date <= end,
        )
    elif dataset == "adjust":
        latest_prior = (
            select(func.max(AdjustFactor.ex_date))
            .where(
                AdjustFactor.code == code,
                AdjustFactor.ex_date < start,
            )
            .scalar_subquery()
        )
        stmt = select(
            func.min(AdjustFactor.fetched_at),
            func.max(AdjustFactor.fetched_at),
        ).where(
            AdjustFactor.code == code,
            or_(
                AdjustFactor.ex_date.between(start, end),
                AdjustFactor.ex_date == latest_prior,
            ),
        )
    elif dataset.startswith("minute:"):
        period = dataset.removeprefix("minute:")
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end, time.max)
        stmt = select(func.min(MinuteBar.fetched_at), func.max(MinuteBar.fetched_at)).where(
            MinuteBar.code == code,
            MinuteBar.period == period,
            MinuteBar.dt >= start_dt,
            MinuteBar.dt <= end_dt,
        )
    else:
        return None, None
    floor, watermark = session.execute(stmt).one()
    return (
        _as_timestamp(floor),
        _as_timestamp(watermark),
    )


def _audit_watermark_matches(
    session: Session,
    run: IngestionRun,
    code: str,
    dataset: str,
    audit: dict,
    request_start: date,
    request_end: date,
) -> bool:
    if audit.get("runId") != run.id:
        return False
    expected_floor = _as_timestamp(audit.get("fetchedAtFloor"))
    expected_watermark = _as_timestamp(audit.get("fetchedAtWatermark"))
    actual_floor, actual_watermark = _dataset_fetched_bounds(
        session,
        code,
        dataset,
        request_start,
        request_end,
    )
    rows = int(audit.get("rows") or 0)
    if dataset == "adjust":
        completed_at = _comparable_timestamp(run.completed_at or run.started_at)
        return bool(
            expected_floor == actual_floor
            and expected_watermark == actual_watermark
            and (
                expected_watermark is None
                or expected_watermark <= completed_at
            )
        )
    if rows == 0:
        return False
    if not all((expected_floor, expected_watermark, actual_floor, actual_watermark)):
        return False
    started_at = _comparable_timestamp(run.started_at)
    completed_at = _comparable_timestamp(run.completed_at or run.started_at)
    return bool(
        expected_floor == actual_floor
        and expected_watermark == actual_watermark
        and started_at <= expected_floor
        and expected_watermark <= completed_at
    )


def _previous_close_row(
    session: Session,
    code: str,
    before: date,
) -> DailyBar | None:
    rows = session.execute(
        select(DailyBar)
        .where(
            DailyBar.code == code,
            DailyBar.trade_date < before,
            DailyBar.close.is_not(None),
            DailyBar.close > 0,
        )
        .order_by(DailyBar.trade_date.desc())
    ).scalars()
    for row in rows:
        try:
            validate_previous_close(
                row.close,
                code=code,
                bar_time=row.trade_date,
            )
        except InvalidOHLCError:
            continue
        return row
    return None


def _minute_previous_close_matches(
    session: Session,
    code: str,
    audit: dict,
    actual_start: date,
) -> bool:
    expected = audit.get("previousClose")
    if not isinstance(expected, dict):
        return False
    current = _previous_close_row(session, code, actual_start)
    if current is None:
        return False
    expected_date = _as_date(expected.get("tradeDate"))
    expected_fetched_at = _as_timestamp(expected.get("fetchedAt"))
    current_fetched_at = _as_timestamp(current.fetched_at)
    if expected_fetched_at is None or current_fetched_at is None:
        return False
    expected_value = expected.get("value")
    try:
        value_matches = math.isclose(
            float(expected_value),
            float(current.close),
            rel_tol=0,
            abs_tol=1e-12,
        )
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        expected_date == current.trade_date
        and expected_fetched_at == current_fetched_at
        and value_matches
    )


def _required_audits_match(
    session: Session,
    run: IngestionRun,
    code: str,
    frequency: str,
    request_start: date,
    request_end: date,
    actual_start: date,
    actual_end: date,
) -> bool:
    datasets = _run_datasets(run)
    primary_key, adjust_key = _required_dataset_keys(frequency)
    primary = datasets.get(primary_key)
    adjust = datasets.get(adjust_key)
    if not isinstance(primary, dict) or not isinstance(adjust, dict):
        return False
    if not _primary_audit_covers(
        primary,
        frequency,
        request_start,
        request_end,
        actual_start,
        actual_end,
    ):
        return False
    if (
        adjust.get("success") is not True
        or adjust.get("period") != "adjust"
        or not _requested_range_covers(adjust, request_start, request_end)
    ):
        return False
    watermarks_match = _audit_watermark_matches(
        session,
        run,
        code,
        primary_key,
        primary,
        request_start,
        request_end,
    ) and _audit_watermark_matches(
        session,
        run,
        code,
        adjust_key,
        adjust,
        request_start,
        request_end,
    )
    if not watermarks_match:
        return False
    return frequency == "1d" or _minute_previous_close_matches(
        session,
        code,
        primary,
        actual_start,
    )


def _run_attempts_required_dataset(
    run: IngestionRun,
    frequency: str,
    request_start: date,
    request_end: date,
    actual_start: date,
    actual_end: date,
) -> bool:
    datasets = _run_datasets(run)
    primary, _ = _required_dataset_keys(frequency)
    audit = datasets.get(primary)
    if not isinstance(audit, dict):
        return False
    if audit.get("success") is False or (
        run.status == "running" and audit.get("success") is not True
    ):
        return True
    return _primary_audit_covers(
        audit,
        frequency,
        request_start,
        request_end,
        actual_start,
        actual_end,
    )


def _run_has_required_failure_or_running(run: IngestionRun, frequency: str) -> bool:
    datasets = _run_datasets(run)
    for key in _required_dataset_keys(frequency):
        audit = datasets.get(key)
        if not isinstance(audit, dict):
            continue
        if audit.get("success") is False:
            return True
        if run.status == "running" and audit.get("success") is not True:
            return True
    return False


def _comparable_timestamp(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ingestion_run_quality_in_session(
    session: Session,
    code: str,
    start: str,
    end: str,
    frequency: str = "1d",
    actual_start: date | datetime | None = None,
    actual_end: date | datetime | None = None,
) -> str | None:
    """Evaluate frequency coverage and later overlapping bad runs in one snapshot."""
    request_start = date.fromisoformat(start[:10])
    request_end = date.fromisoformat(end[:10])
    actual_start_date = _as_date(actual_start) or request_start
    actual_end_date = _as_date(actual_end) or request_end
    try:
        runs = list(
            session.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.code == code,
                    IngestionRun.start_date <= request_end,
                    IngestionRun.end_date >= request_start,
                )
                .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
            ).scalars().all()
        )
    except (OperationalError, ProgrammingError) as exc:
        if _is_missing_ingestion_table(exc):
            return "untracked"
        raise

    covering_ready = next(
        (
            run
            for run in runs
            if run.status in {"ready", "partial"}
            and _required_audits_match(
                session,
                run,
                code,
                frequency,
                request_start,
                request_end,
                actual_start_date,
                actual_end_date,
            )
        ),
        None,
    )
    if covering_ready is None:
        return (
            "partial_ingestion"
            if any(
                _run_attempts_required_dataset(
                    run,
                    frequency,
                    request_start,
                    request_end,
                    actual_start_date,
                    actual_end_date,
                )
                for run in runs
            )
            else "untracked"
        )

    ready_watermark = covering_ready.completed_at or covering_ready.started_at
    if any(
        _run_has_required_failure_or_running(run, frequency)
        and _comparable_timestamp(run.started_at) > _comparable_timestamp(ready_watermark)
        for run in runs
    ):
        return "partial_ingestion"
    return None


def ingestion_run_quality(
    code: str,
    start: str,
    end: str,
    frequency: str = "1d",
) -> str | None:
    """Return audit quality outside a combined market-data read."""
    with SessionLocal() as session:
        return _ingestion_run_quality_in_session(session, code, start, end, frequency)


def _adjust_points(
    session: Session,
    code: str,
    start: str,
    end: str,
) -> list[tuple[date, float]]:
    """Load the latest pre-start factor plus factors inside the request."""
    start_date = date.fromisoformat(start[:10])
    end_date = date.fromisoformat(end[:10])
    latest_prior = (
        select(func.max(AdjustFactor.ex_date))
        .where(
            AdjustFactor.code == code,
            AdjustFactor.ex_date < start_date,
        )
        .scalar_subquery()
    )
    rows = list(
        session.execute(
            select(AdjustFactor.ex_date, AdjustFactor.back_adjust_factor)
            .where(
                AdjustFactor.code == code,
                or_(
                    AdjustFactor.ex_date.between(start_date, end_date),
                    AdjustFactor.ex_date == latest_prior,
                ),
            )
            .order_by(AdjustFactor.ex_date)
        ).all()
    )
    points: list[tuple[date, float]] = []
    for factor_date, factor in rows:
        if factor is None:
            continue
        if isinstance(factor, bool):
            raise InvalidOHLCError(
                code=code,
                bar_time=factor_date,
                reason="invalid_adjustment_factor",
            )
        try:
            number = float(factor)
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidOHLCError(
                code=code,
                bar_time=factor_date,
                reason="invalid_adjustment_factor",
            ) from exc
        if not math.isfinite(number) or number <= 0:
            raise InvalidOHLCError(
                code=code,
                bar_time=factor_date,
                reason="invalid_adjustment_factor",
            )
        points.append((factor_date, number))
    return points


def _factor_at(points: list[tuple[date, float]], days: list[date], on: date) -> float:
    """取 ex_date <= on 的最近后复权因子。

    早于首个已知除权点时**沿用首个因子**（而非 1.0）：baostock 的 backAdjustFactor 是自上市
    累积的非归一化系数，回测区间起点之前的除权点未必回填；若回退到 1.0，会在首个除权点
    造成数十倍的虚假跳变（伪造涨停级别的假收益）。沿用首个因子保证区间内后复权价连续，
    真实除权日仍按相邻因子比值产生正常的小幅补偿。
    """
    i = bisect.bisect_right(days, on) - 1
    return points[i][1] if i >= 0 else points[0][1]


def _instrument_list_date(session: Session, code: str) -> date | None:
    """读取上市日；旧库尚无 instruments 表时按代码/日期规则保守降级。"""
    try:
        if not inspect(session.get_bind()).has_table(Instrument.__tablename__):
            return None
        return session.execute(
            select(Instrument.list_date).where(Instrument.code == code)
        ).scalar_one_or_none()
    except (OperationalError, ProgrammingError):
        return None


def _load_hfq_bars_in_session(
    session: Session,
    code: str,
    start: str,
    end: str,
) -> tuple[list[Bar], str]:
    rows = list(
        session.execute(
            select(DailyBar)
            .where(DailyBar.code == code, DailyBar.trade_date >= start, DailyBar.trade_date <= end)
            .order_by(DailyBar.trade_date)
        ).scalars().all()
    )
    try:
        checked_rows = [
            validate_ohlc(
                open_value=row.open,
                high_value=row.high,
                low_value=row.low,
                close_value=row.close,
                volume=row.volume,
                amount=row.amount,
                code=code,
                bar_time=row.trade_date,
            )
            for row in rows
        ]
        points = _adjust_points(session, code, start, end)
    except InvalidOHLCError:
        return [], "invalid_ohlc"
    # Historical ST status is not present in the current PIT schema. Never
    # apply today's name backwards; use only list_date plus code/date rules.
    list_date = _instrument_list_date(session, code)
    point_days = [d for d, _ in points]
    coverage = "full" if points else "none"
    # 归一化基准：以区间首个 bar 适用的因子为基准，使后复权价从原始价量级起算
    # （整体缩放不影响收益率/信号，但更直观、与原始价可比，并避免巨大数值）。
    base = _factor_at(points, point_days, rows[0].trade_date) if (points and rows) else 1.0
    bars: list[Bar] = []
    try:
        for row, checked in zip(rows, checked_rows, strict=True):
            factor = (
                _factor_at(points, point_days, row.trade_date) / base if points else 1.0
            )
            adjusted = validate_ohlc(
                open_value=round(float(checked.open) * factor, 4),
                high_value=round(float(checked.high) * factor, 4),
                low_value=round(float(checked.low) * factor, 4),
                close_value=round(float(checked.close) * factor, 4),
                volume=checked.volume,
                amount=checked.amount,
                code=code,
                bar_time=row.trade_date,
            )
            bars.append(
                Bar(
                    code=code,
                    date=row.trade_date,
                    open=float(adjusted.open),
                    high=float(adjusted.high),
                    low=float(adjusted.low),
                    close=float(adjusted.close),
                    volume=(
                        int(adjusted.volume) if adjusted.volume is not None else None
                    ),
                    amount=(
                        float(adjusted.amount)
                        if adjusted.amount is not None
                        else None
                    ),
                    limit_ratio=rules.price_limit_ratio(
                        code,
                        trade_date=row.trade_date,
                        list_date=list_date,
                    ),
                )
            )
    except InvalidOHLCError:
        return [], "invalid_ohlc"
    return bars, coverage


def load_hfq_bars(code: str, start: str, end: str) -> tuple[list[Bar], str]:
    """加载后复权日线。返回 ``(bars, coverage)``；coverage: ``full`` / ``none``。

    - 有复权因子：OHLC × 对应阶梯后复权因子（``full``）。
    - 无任何复权因子：返回原始 OHLC，标注 ``none``（调用方据此提示数据质量）。
    """
    with SessionLocal() as session:
        return _load_hfq_bars_in_session(session, code, start, end)


_MINUTE_PERIODS = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}


def _load_minute_bars_in_session(
    session: Session,
    code: str,
    frequency: str,
    start: str,
    end: str,
) -> tuple[list[Bar], str]:
    """加载指定周期的后复权分钟线，不触发任何实时数据抓取。

    分钟 OHLC 使用该分钟所属自然交易日适用的后复权因子；成交量与成交额保持原值。
    返回 ``coverage`` 为 ``full``（有复权因子）、``none``（无因子）或
    ``missing``（指定标的/周期/区间没有分钟数据）。
    """
    period = _MINUTE_PERIODS.get(frequency)
    if period is None:
        raise ValueError(f"不支持的分钟回测周期: {frequency}")
    start_dt = datetime.combine(date.fromisoformat(start[:10]), time.min)
    end_dt = datetime.combine(date.fromisoformat(end[:10]), time.max)
    rows = list(
        session.execute(
            select(MinuteBar)
            .where(
                MinuteBar.code == code,
                MinuteBar.period == period,
                MinuteBar.dt >= start_dt,
                MinuteBar.dt <= end_dt,
            )
            .order_by(MinuteBar.dt)
        ).scalars().all()
    )
    try:
        checked_rows = [
            validate_ohlc(
                open_value=row.open,
                high_value=row.high,
                low_value=row.low,
                close_value=row.close,
                volume=row.volume,
                amount=row.amount,
                code=code,
                bar_time=row.dt,
            )
            for row in rows
        ]
        points = _adjust_points(session, code, start, end)
    except InvalidOHLCError:
        return [], "invalid_ohlc"
    list_date = _instrument_list_date(session, code)
    previous_row = (
        _previous_close_row(session, code, rows[0].dt.date())
        if rows
        else None
    )

    if not rows:
        return [], "missing"
    point_days = [d for d, _ in points]
    first_day = rows[0].dt.date()
    base = _factor_at(points, point_days, first_day) if points else 1.0
    previous_close = None
    if previous_row is not None:
        try:
            raw_previous_close = validate_previous_close(
                previous_row.close,
                code=code,
                bar_time=previous_row.trade_date,
            )
            previous_factor = (
                _factor_at(points, point_days, previous_row.trade_date) / base
                if points
                else 1.0
            )
            previous_close = validate_previous_close(
                round(float(raw_previous_close) * previous_factor, 4),
                code=code,
                bar_time=previous_row.trade_date,
            )
        except InvalidOHLCError:
            return [], "invalid_ohlc"
    coverage = (
        "missing_previous_close"
        if previous_close is None or previous_close <= 0
        else ("full" if points else "none")
    )
    bars: list[Bar] = []
    try:
        for index, (row, checked) in enumerate(
            zip(rows, checked_rows, strict=True)
        ):
            factor = (
                _factor_at(points, point_days, row.dt.date()) / base
                if points
                else 1.0
            )
            adjusted = validate_ohlc(
                open_value=round(float(checked.open) * factor, 4),
                high_value=round(float(checked.high) * factor, 4),
                low_value=round(float(checked.low) * factor, 4),
                close_value=round(float(checked.close) * factor, 4),
                volume=checked.volume,
                amount=checked.amount,
                code=code,
                bar_time=row.dt,
            )
            bars.append(
                Bar(
                    code=code,
                    date=row.dt,
                    open=float(adjusted.open),
                    high=float(adjusted.high),
                    low=float(adjusted.low),
                    close=float(adjusted.close),
                    volume=(
                        int(adjusted.volume) if adjusted.volume is not None else None
                    ),
                    amount=(
                        float(adjusted.amount)
                        if adjusted.amount is not None
                        else None
                    ),
                    previous_close=(
                        float(previous_close)
                        if index == 0 and previous_close is not None
                        else None
                    ),
                    limit_ratio=rules.price_limit_ratio(
                        code,
                        trade_date=row.dt.date(),
                        list_date=list_date,
                    ),
                )
            )
    except InvalidOHLCError:
        return [], "invalid_ohlc"
    return bars, coverage


def load_minute_bars(
    code: str,
    frequency: str,
    start: str,
    end: str,
) -> tuple[list[Bar], str]:
    with SessionLocal() as session:
        return _load_minute_bars_in_session(session, code, frequency, start, end)


def _begin_consistent_read(session: Session) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    elif dialect == "sqlite":
        session.connection().exec_driver_sql("BEGIN")
    else:
        session.connection()


def load_bars_with_quality(
    code: str,
    frequency: str,
    start: str,
    end: str,
) -> tuple[list[Bar], str]:
    """Load bars and ingestion quality from one repeatable database snapshot."""
    with SessionLocal() as session:
        _begin_consistent_read(session)
        if frequency == "1d":
            bars, coverage = _load_hfq_bars_in_session(session, code, start, end)
        else:
            bars, coverage = _load_minute_bars_in_session(
                session,
                code,
                frequency,
                start,
                end,
            )
        if coverage == "invalid_ohlc":
            return [], coverage
        snapshot_quality = _ingestion_run_quality_in_session(
            session,
            code,
            start,
            end,
            frequency,
            actual_start=bars[0].date if bars else None,
            actual_end=bars[-1].date if bars else None,
        )
        if snapshot_quality == "partial_ingestion":
            coverage = snapshot_quality
        elif snapshot_quality == "untracked" and coverage not in {
            "missing",
            "missing_previous_close",
        }:
            coverage = snapshot_quality
        return bars, coverage
