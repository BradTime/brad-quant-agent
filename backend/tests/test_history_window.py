"""H21：history 窗口用 bars[max(0,i-n):i]，语义与旧切片一致。"""

from __future__ import annotations

from datetime import date, timedelta

from app.backtest.base import BacktestConfig
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine


class _CaptureHistoryStrategy:
    def __init__(self) -> None:
        self.windows: list[list[float]] = []

    def initialize(self, ctx) -> None:  # noqa: ANN001
        return None

    def handle_bar(self, ctx, bars_today) -> None:  # noqa: ANN001
        closes = ctx.history("600000.SH", "close", 5)
        self.windows.append(closes)


def _bars(n: int) -> list[Bar]:
    start = date(2024, 1, 1)
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        px = 10.0 + i
        out.append(
            Bar(
                code="600000.SH",
                date=d,
                open=px,
                high=px,
                low=px,
                close=px,
                volume=1000,
                amount=px * 1000,
                previous_close=px - 1 if i else None,
            )
        )
    return out


def test_native_history_window_matches_tail_semantics():
    bars = _bars(20)
    strategy = _CaptureHistoryStrategy()
    NativeEngine().run(
        BacktestConfig(
            strategy_type="dual_ma",
            params={},
            codes=["600000.SH"],
            start="2024-01-01",
            end="2024-01-20",
            initial_capital=100_000,
            slippage=0,
            engine="native",
            frequency="1d",
        ),
        strategy,
        {"600000.SH": bars},
    )
    # 第 10 根 bar（0-based index 9，asof 后 i=10）→ close[5:10]
    assert strategy.windows[9] == [15.0, 16.0, 17.0, 18.0, 19.0]
    assert all(len(w) <= 5 for w in strategy.windows)
