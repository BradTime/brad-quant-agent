"""Long-only rolling z-score mean reversion with entry/exit hysteresis."""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class ZScoreReversion(Strategy):
    def initialize(self, ctx) -> None:
        self.period = int(ctx.params.get("period", 20))
        self.entry_z = float(ctx.params.get("entryZ", -2.0))
        self.exit_z = float(ctx.params.get("exitZ", 0.0))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        count = len(ctx.universe) or len(bars)
        if not count:
            return
        target = self.target / count
        for code in bars:
            closes = ctx.history(code, "close", self.period)
            if len(closes) < self.period:
                continue
            mean = sum(closes) / self.period
            std = (
                sum((value - mean) ** 2 for value in closes) / self.period
            ) ** 0.5
            if std == 0:
                continue
            zscore = (closes[-1] - mean) / std
            if zscore <= self.entry_z:
                ctx.order_target_percent(code, target)
            elif zscore >= self.exit_z:
                ctx.order_target_percent(code, 0.0)
