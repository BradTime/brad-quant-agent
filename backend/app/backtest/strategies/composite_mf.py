"""Cross-sectional price/volume composite factor.

This first M2 slice intentionally uses only PIT-safe OHLCV fields. Fundamental
quality/value factors are added only after their as-of panel is wired.
"""

from __future__ import annotations

import math

from app.backtest.base import Strategy
from app.backtest.data import Bar


def _zscore(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    mean = sum(values.values()) / len(values)
    std = (
        sum((value - mean) ** 2 for value in values.values()) / len(values)
    ) ** 0.5
    if std == 0:
        return {code: 0.0 for code in values}
    return {code: (value - mean) / std for code, value in values.items()}


class CompositeMultiFactor(Strategy):
    def initialize(self, ctx) -> None:
        self.lookback = int(ctx.params.get("lookback", 60))
        self.top_n = int(ctx.params.get("topN", 5))
        self.weight_momentum = float(ctx.params.get("wMom", 0.4))
        self.weight_low_vol = float(ctx.params.get("wLowVol", 0.3))
        self.weight_liquidity = float(ctx.params.get("wLiq", 0.3))
        self.target = float(ctx.params.get("target", 0.95))

    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None:
        momentum: dict[str, float] = {}
        low_volatility: dict[str, float] = {}
        liquidity: dict[str, float] = {}
        for code in bars:
            closes = ctx.history(code, "close", self.lookback + 1)
            amounts = ctx.history(code, "amount", self.lookback)
            volumes = ctx.history(code, "volume", self.lookback)
            if len(closes) < self.lookback + 1 or closes[0] <= 0:
                continue
            returns = [
                closes[index] / closes[index - 1] - 1
                for index in range(1, len(closes))
                if closes[index - 1] > 0
            ]
            if len(returns) != self.lookback:
                continue
            mean_return = sum(returns) / len(returns)
            volatility = (
                sum((value - mean_return) ** 2 for value in returns)
                / len(returns)
            ) ** 0.5
            usable_amounts = [
                float(value)
                for value in amounts
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) > 0
            ]
            if len(usable_amounts) != self.lookback:
                usable_volumes = [
                    float(value)
                    for value in volumes
                    if isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    and float(value) > 0
                ]
                if len(usable_volumes) != self.lookback:
                    continue
                usable_amounts = [
                    volume * close
                    for volume, close in zip(
                        usable_volumes, closes[-self.lookback :], strict=True
                    )
                ]
            momentum[code] = closes[-1] / closes[0] - 1
            low_volatility[code] = -volatility
            liquidity[code] = sum(math.log(value) for value in usable_amounts) / len(
                usable_amounts
            )
        if len(momentum) < 3:
            return
        z_momentum = _zscore(momentum)
        z_low_volatility = _zscore(low_volatility)
        z_liquidity = _zscore(liquidity)
        scores = {
            code: (
                self.weight_momentum * z_momentum[code]
                + self.weight_low_vol * z_low_volatility[code]
                + self.weight_liquidity * z_liquidity[code]
            )
            for code in momentum
        }
        selected = {
            code
            for code, _ in sorted(
                scores.items(), key=lambda item: item[1], reverse=True
            )[: self.top_n]
        }
        per_target = self.target / len(selected)
        for code in scores:
            ctx.order_target_percent(
                code, per_target if code in selected else 0.0
            )
