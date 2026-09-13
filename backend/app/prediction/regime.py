"""Auditable rule-first market regime classifier."""

from __future__ import annotations

import math
from typing import Any, Literal

MarketRegime = Literal["bull", "bear", "range", "risk_off"]
REGIME_RULES_VERSION = "regime-rules-v1"


def classify_market_regime(
    *,
    index_closes: list[float],
    market_breadth: float,
) -> dict[str, Any]:
    if len(index_closes) < 60:
        raise ValueError("市场状态分类至少需要 60 个交易日")
    if any(value <= 0 or not math.isfinite(value) for value in index_closes):
        raise ValueError("指数收盘价必须是正的有限数")
    if not 0 <= market_breadth <= 1:
        raise ValueError("市场宽度必须在 [0,1]")
    window = index_closes[-60:]
    moving_average = sum(window) / len(window)
    trend = window[-1] / moving_average - 1
    returns = [
        window[index] / window[index - 1] - 1
        for index in range(1, len(window))
    ]
    mean_return = sum(returns) / len(returns)
    annualized_volatility = math.sqrt(
        sum((value - mean_return) ** 2 for value in returns)
        / len(returns)
    ) * math.sqrt(252)
    if annualized_volatility >= 0.3:
        regime: MarketRegime = "risk_off"
    elif trend >= 0.03 and market_breadth >= 0.55:
        regime = "bull"
    elif trend <= -0.03 and market_breadth <= 0.45:
        regime = "bear"
    else:
        regime = "range"
    return {
        "regime": regime,
        "rulesVersion": REGIME_RULES_VERSION,
        "evidence": {
            "priceVsMa60": trend,
            "annualizedVolatility60": annualized_volatility,
            "marketBreadth": market_breadth,
        },
    }
