"""回测数据加载：后复权(HFQ)日线/分钟线 + 交易日历。

回测必须用**后复权**价才能正确跨除权日（后复权不改变历史相对收益，适合回测）。
读 ``daily_bars`` / ``minute_bars``（不复权 OHLC）+ ``adjust_factors``
（后复权因子，按 ex_date 阶梯），输出复权后的 ``Bar`` 序列。缺因子的标的标注
``coverage``（延续"不杜撰、显式标缺口"原则）。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import distinct, select

from app.db.session import SessionLocal
from app.models.market import AdjustFactor, DailyBar, MinuteBar


@dataclass
class Bar:
    code: str
    date: date | datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    previous_close: float | None = None


def _f(x) -> float:
    return float(x) if x is not None else 0.0


def trading_calendar(start: str, end: str) -> list[date]:
    """用已落库 ``daily_bars`` 的去重交易日近似交易日历（区间内所有标的的并集）。"""
    with SessionLocal() as session:
        stmt = (
            select(distinct(DailyBar.trade_date))
            .where(DailyBar.trade_date >= start, DailyBar.trade_date <= end)
            .order_by(DailyBar.trade_date)
        )
        return [d for (d,) in session.execute(stmt).all()]


def _adjust_points(session, code: str) -> list[tuple[date, float]]:
    """该标的的 (ex_date, back_adjust_factor) 升序列表；无则空。"""
    rows = list(
        session.execute(
            select(AdjustFactor.ex_date, AdjustFactor.back_adjust_factor)
            .where(AdjustFactor.code == code)
            .order_by(AdjustFactor.ex_date)
        ).all()
    )
    return [(d, float(f)) for d, f in rows if f is not None]


def _factor_at(points: list[tuple[date, float]], days: list[date], on: date) -> float:
    """取 ex_date <= on 的最近后复权因子。

    早于首个已知除权点时**沿用首个因子**（而非 1.0）：baostock 的 backAdjustFactor 是自上市
    累积的非归一化系数，回测区间起点之前的除权点未必回填；若回退到 1.0，会在首个除权点
    造成数十倍的虚假跳变（伪造涨停级别的假收益）。沿用首个因子保证区间内后复权价连续，
    真实除权日仍按相邻因子比值产生正常的小幅补偿。
    """
    i = bisect.bisect_right(days, on) - 1
    return points[i][1] if i >= 0 else points[0][1]


def load_hfq_bars(code: str, start: str, end: str) -> tuple[list[Bar], str]:
    """加载后复权日线。返回 ``(bars, coverage)``；coverage: ``full`` / ``none``。

    - 有复权因子：OHLC × 对应阶梯后复权因子（``full``）。
    - 无任何复权因子：返回原始 OHLC，标注 ``none``（调用方据此提示数据质量）。
    """
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(DailyBar)
                .where(DailyBar.code == code, DailyBar.trade_date >= start, DailyBar.trade_date <= end)
                .order_by(DailyBar.trade_date)
            ).scalars().all()
        )
        points = _adjust_points(session, code)

    point_days = [d for d, _ in points]
    coverage = "full" if points else "none"
    # 归一化基准：以区间首个 bar 适用的因子为基准，使后复权价从原始价量级起算
    # （整体缩放不影响收益率/信号，但更直观、与原始价可比，并避免巨大数值）。
    base = (_factor_at(points, point_days, rows[0].trade_date) if (points and rows) else 1.0) or 1.0
    bars: list[Bar] = []
    for r in rows:
        factor = (_factor_at(points, point_days, r.trade_date) / base) if points else 1.0
        bars.append(
            Bar(
                code=code,
                date=r.trade_date,
                open=round(_f(r.open) * factor, 4),
                high=round(_f(r.high) * factor, 4),
                low=round(_f(r.low) * factor, 4),
                close=round(_f(r.close) * factor, 4),
                volume=r.volume or 0,
                amount=_f(r.amount),
            )
        )
    return bars, coverage


_MINUTE_PERIODS = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}


def load_minute_bars(
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
    with SessionLocal() as session:
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
        points = _adjust_points(session, code)
        previous_row = (
            session.execute(
                select(DailyBar)
                .where(
                    DailyBar.code == code,
                    DailyBar.trade_date < rows[0].dt.date(),
                )
                .order_by(DailyBar.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if rows
            else None
        )

    if not rows:
        return [], "missing"
    point_days = [d for d, _ in points]
    coverage = "full" if points else "none"
    first_day = rows[0].dt.date()
    base = (_factor_at(points, point_days, first_day) if points else 1.0) or 1.0
    previous_close = None
    if previous_row is not None and previous_row.close is not None:
        previous_factor = (
            _factor_at(points, point_days, previous_row.trade_date) / base if points else 1.0
        )
        previous_close = round(_f(previous_row.close) * previous_factor, 4)
    bars: list[Bar] = []
    for index, row in enumerate(rows):
        factor = (_factor_at(points, point_days, row.dt.date()) / base) if points else 1.0
        bars.append(
            Bar(
                code=code,
                date=row.dt,
                open=round(_f(row.open) * factor, 4),
                high=round(_f(row.high) * factor, 4),
                low=round(_f(row.low) * factor, 4),
                close=round(_f(row.close) * factor, 4),
                volume=row.volume or 0,
                amount=_f(row.amount),
                previous_close=previous_close if index == 0 else None,
            )
        )
    return bars, coverage
