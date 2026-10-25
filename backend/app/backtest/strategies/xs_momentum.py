"""Cross-sectional momentum rotation over the configured PIT universe."""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class CrossSectionalMomentum(Strategy):
    def initialize(self, ctx) -> None:
        self.lookback = int(ctx.params.get("lookback", 60))
        self.top_n = int(ctx.params.get("topN", 3))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        momentum: list[tuple[float, str]] = []
        for code in bars:
            closes = ctx.history(code, "close", self.lookback + 1)
            if len(closes) < self.lookback + 1 or closes[0] <= 0:
                continue
            momentum.append((closes[-1] / closes[0] - 1, code))
        if not momentum:
            return
        selected = {
            code
            for _, code in sorted(momentum, reverse=True)[: self.top_n]
        }
        per_target = self.target / len(selected)
        for _, code in momentum:
            ctx.order_target_percent(
                code, per_target if code in selected else 0.0
            )
