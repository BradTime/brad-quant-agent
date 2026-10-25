"""Donchian breakout using only bars visible at the current close."""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


class DonchianBreakout(Strategy):
    def initialize(self, ctx) -> None:
        self.channel = int(ctx.params.get("channel", 20))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        count = len(ctx.universe) or len(bars)
        if not count:
            return
        target = self.target / count
        for code in bars:
            highs = ctx.history(code, "high", self.channel + 1)
            lows = ctx.history(code, "low", self.channel + 1)
            closes = ctx.history(code, "close", self.channel + 1)
            if min(len(highs), len(lows), len(closes)) < self.channel + 1:
                continue
            if closes[-1] > max(highs[:-1]):
                ctx.order_target_percent(code, target)
            elif closes[-1] < min(lows[:-1]):
                ctx.order_target_percent(code, 0.0)
