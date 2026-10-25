"""Cross-sectional PIT value/quality strategy using available financial vintages."""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.data import Bar


def _zscore(values: dict[str, float]) -> dict[str, float]:
    mean = sum(values.values()) / len(values)
    std = (
        sum((value - mean) ** 2 for value in values.values()) / len(values)
    ) ** 0.5
    if std == 0:
        return {code: 0.0 for code in values}
    return {code: (value - mean) / std for code, value in values.items()}


class FundamentalQuality(Strategy):
    def initialize(self, ctx) -> None:
        self.top_n = int(ctx.params.get("topN", 5))
        self.weight_value = float(ctx.params.get("wValue", 0.5))
        self.weight_quality = float(ctx.params.get("wQuality", 0.5))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        value_factor: dict[str, float] = {}
        quality_factor: dict[str, float] = {}
        for code, bar in bars.items():
            rows = ctx.panel_history(code, "financials", 1)
            if not rows or bar.close <= 0:
                continue
            latest = rows[-1]
            bps = latest.get("bps")
            roe = latest.get("roe")
            if not isinstance(bps, (int, float)) or not isinstance(
                roe, (int, float)
            ):
                continue
            value_factor[code] = float(bps) / bar.close
            quality_factor[code] = float(roe)
        if len(value_factor) < 3:
            for code in bars:
                ctx.order_target_percent(code, 0.0)
            return
        value_z = _zscore(value_factor)
        quality_z = _zscore(quality_factor)
        scores = {
            code: (
                self.weight_value * value_z[code]
                + self.weight_quality * quality_z[code]
            )
            for code in value_factor
        }
        selected = {
            code
            for code, _ in sorted(
                scores.items(), key=lambda item: item[1], reverse=True
            )[: self.top_n]
        }
        per_target = self.target / len(selected)
        for code in bars:
            ctx.order_target_percent(
                code, per_target if code in selected else 0.0
            )
