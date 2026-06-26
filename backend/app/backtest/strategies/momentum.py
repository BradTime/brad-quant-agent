"""动量策略：过去 lookback 日收益为正则持有、为负则清仓（趋势延续）。

参数：``lookback``(回看天数,默认20) / ``target``(目标总仓位,默认0.95)。
仅用 ``ctx.history``（截至当日），无未来函数。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class Momentum(Strategy):
    def initialize(self, ctx) -> None:
        self.lookback = max(int(ctx.params.get("lookback", 20)), 1)
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        n = len(bars)
        if not n:
            return
        per = self.target / n
        for code in bars:
            closes = ctx.history(code, "close", self.lookback + 1)
            if len(closes) < self.lookback + 1:
                continue
            past = closes[-self.lookback - 1]
            mom = (closes[-1] / past - 1) if past > 0 else 0.0
            ctx.order_target_percent(code, per if mom > 0 else 0.0)
