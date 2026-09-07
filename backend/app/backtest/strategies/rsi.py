"""RSI 均值回归策略：RSI 超卖建/满仓、超买清仓。

参数：``period``(默认14) / ``low``(超卖阈值,默认30) / ``high``(超买阈值,默认70) /
``target``(目标总仓位,默认0.95)。仅用 ``ctx.history``（截至当日），无未来函数。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


def _rsi(closes: list[float], period: int) -> float:
    """经典 RSI（简单平均版）：基于最近 period 个收益的涨跌均值。"""
    gains = 0.0
    losses = 0.0
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


class RSI(Strategy):
    def initialize(self, ctx) -> None:
        self.period = max(int(ctx.params.get("period", 14)), 2)
        self.low = float(ctx.params.get("low", 30))
        self.high = float(ctx.params.get("high", 70))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        n = len(ctx.universe) or len(bars)
        if not n:
            return
        per = self.target / n
        for code in bars:
            closes = ctx.history(code, "close", self.period + 1)
            if len(closes) < self.period + 1:
                continue
            rsi = _rsi(closes, self.period)
            if rsi < self.low:
                ctx.order_target_percent(code, per)  # 超卖买入
            elif rsi > self.high:
                ctx.order_target_percent(code, 0.0)  # 超买清仓
