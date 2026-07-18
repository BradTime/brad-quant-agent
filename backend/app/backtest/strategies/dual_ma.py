"""双均线策略：快线上穿慢线则建/满仓，下穿则清仓。支持单/多标的（多标的等权均分）。

参数：``fast``(默认5) / ``slow``(默认20) / ``target``(目标总仓位，默认0.95)。
仅用 ``ctx.history``（截至当日）计算均线，无未来函数。
"""

from __future__ import annotations

import math

from app.backtest.base import Strategy
from app.backtest.data import Bar


class DualMA(Strategy):
    def initialize(self, ctx) -> None:
        fast = ctx.params.get("fast", 5)
        slow = ctx.params.get("slow", 20)
        target = ctx.params.get("target", 0.95)
        if type(fast) is not int or not 1 <= fast <= 120:
            raise ValueError("参数 fast 必须是 1 到 120 的整数")
        if type(slow) is not int or not 2 <= slow <= 250:
            raise ValueError("参数 slow 必须是 2 到 250 的整数")
        if fast >= slow:
            raise ValueError("参数 fast 必须小于 slow")
        if (
            isinstance(target, bool)
            or not isinstance(target, (int, float))
            or not math.isfinite(float(target))
            or not 0.1 <= float(target) <= 1.0
        ):
            raise ValueError("参数 target 必须是 0.1 到 1.0 的有限数字")
        self.fast = fast
        self.slow = slow
        self.target = float(target)

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
