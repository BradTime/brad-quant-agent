"""回测数据加载：后复权(HFQ)日线 + 交易日历。

回测必须用**后复权**价才能正确跨除权日（后复权不改变历史相对收益，适合回测）。
读 ``daily_bars``（不复权 OHLC）+ ``adjust_factors``（后复权因子，按 ex_date 阶梯），
输出复权后的 ``Bar`` 序列。缺因子的标的标注 ``coverage``（延续"不杜撰、显式标缺口"原则）。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date

from sqlalchemy import distinct, select

from app.db.session import SessionLocal
from app.models.market import AdjustFactor, DailyBar


@dataclass
class Bar:
    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float


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
    """取 ex_date <= on 的最近后复权因子；若早于首个 ex_date 则用 1.0。"""
    i = bisect.bisect_right(days, on) - 1
    return points[i][1] if i >= 0 else 1.0


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
    bars: list[Bar] = []
    for r in rows:
        factor = _factor_at(points, point_days, r.trade_date) if points else 1.0
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
