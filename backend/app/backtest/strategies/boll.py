"""布林带策略：价格触下轨建/满仓、触上轨清仓（均值回归）。

参数：``period``(默认20) / ``k``(标准差倍数,默认2.0) / ``target``(目标总仓位,默认0.95)。
仅用 ``ctx.history``（截至当日），无未来函数。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class Boll(Strategy):
    def initialize(self, ctx) -> None:
        self.period = max(int(ctx.params.get("period", 20)), 2)
        self.k = float(ctx.params.get("k", 2.0))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        n = len(bars)
        if not n:
            return
        per = self.target / n
        for code in bars:
            closes = ctx.history(code, "close", self.period)
            if len(closes) < self.period:
                continue
            ma = sum(closes) / len(closes)
            std = (sum((c - ma) ** 2 for c in closes) / len(closes)) ** 0.5
            price = closes[-1]
            if price < ma - self.k * std:
                ctx.order_target_percent(code, per)  # 触下轨买入
            elif price > ma + self.k * std:
                ctx.order_target_percent(code, 0.0)  # 触上轨清仓
