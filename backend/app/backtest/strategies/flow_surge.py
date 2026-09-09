"""Append-only PIT capital-flow event strategy."""

from __future__ import annotations

from datetime import date

from app.backtest.base import Strategy
from app.backtest.data import Bar


class FlowSurge(Strategy):
    def initialize(self, ctx) -> None:
        self.window = int(ctx.params.get("window", 3))
        self.min_ratio = float(ctx.params.get("minRatio", 5.0))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        count = len(ctx.universe) or len(bars)
        if not count:
            return
        target = self.target / count
        current = (
            ctx.current_date.date()
            if hasattr(ctx.current_date, "date")
            else ctx.current_date
        )
        for code in bars:
            rows = ctx.panel_history(code, "capital_flow", self.window)
            row_dates = [date.fromisoformat(row["date"][:10]) for row in rows]
            ratios = [row.get("mainNetRatio") for row in rows]
            complete = (
                len(rows) == self.window
                and row_dates[-1] == current
                and all(isinstance(value, (int, float)) for value in ratios)
            )
            ctx.order_target_percent(
                code,
                target
                if complete
                and all(float(value) >= self.min_ratio for value in ratios)
                else 0.0,
            )
