"""双均线策略：快线上穿慢线则建/满仓，下穿则清仓。支持单/多标的（多标的等权均分）。

参数：``fast``(默认5) / ``slow``(默认20) / ``target``(目标总仓位，默认0.95)。
仅用 ``ctx.history``（截至当日）计算均线，无未来函数。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class DualMA(Strategy):
    def initialize(self, ctx) -> None:
        self.fast = max(int(ctx.params.get("fast", 5)), 1)
        self.slow = max(int(ctx.params.get("slow", 20)), 2)
        if self.fast >= self.slow:  # 非法参数兜底
            self.fast, self.slow = 5, 20
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        n = len(ctx.universe) or len(bars)
        if not n:
            return
        per = self.target / n  # 多标的等权
        for code in bars:
            closes = ctx.history(code, "close", self.slow)
            if len(closes) < self.slow:
                continue  # 数据不足，跳过（不下单）
            fast_ma = sum(closes[-self.fast :]) / self.fast
            slow_ma = sum(closes[-self.slow :]) / self.slow
            ctx.order_target_percent(code, per if fast_ma > slow_ma else 0.0)
