"""Unified signal protocol for built-in and restricted custom strategies."""

from __future__ import annotations

import math
from typing import Any

from app.providers.symbols import normalize_a_share_code
from app.services.strategy import validate_params
from app.services.strategy_sandbox import PROTOCOL_VERSION, run_source


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _closes(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get("close")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
        ):
            values.append(float(value))
    return values


def _rsi(values: list[float], period: int) -> float:
    gains = 0.0
    losses = 0.0
    for index in range(len(values) - period, len(values)):
        difference = values[index] - values[index - 1]
        if difference >= 0:
            gains += difference
        else:
            losses -= difference
    if losses == 0:
        return 100.0
    relative = gains / losses
    return 100.0 - 100.0 / (1.0 + relative)


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


def _composite_signals(
    normalized: dict[str, int | float],
    bars: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    lookback = int(normalized["lookback"])
    momentum: dict[str, float] = {}
    low_volatility: dict[str, float] = {}
    liquidity: dict[str, float] = {}
    for raw_code, rows in bars.items():
        code = normalize_a_share_code(raw_code)
        closes = _closes(rows)
        amounts = [
            float(row["amount"])
            for row in rows[-lookback:]
            if isinstance(row.get("amount"), (int, float))
            and not isinstance(row.get("amount"), bool)
            and math.isfinite(float(row["amount"]))
            and float(row["amount"]) > 0
        ]
        if len(closes) < lookback + 1 or len(amounts) != lookback:
            continue
        window = closes[-lookback - 1 :]
        returns = [
            window[index] / window[index - 1] - 1
            for index in range(1, len(window))
        ]
        mean_return = sum(returns) / lookback
        volatility = (
            sum((value - mean_return) ** 2 for value in returns) / lookback
        ) ** 0.5
        momentum[code] = window[-1] / window[0] - 1
        low_volatility[code] = -volatility
        liquidity[code] = sum(math.log(value) for value in amounts) / lookback
    if len(momentum) < 3:
        return []
    z_momentum = _zscore(momentum)
    z_low_volatility = _zscore(low_volatility)
    z_liquidity = _zscore(liquidity)
    return [
        {
            "code": code,
            "score": _clamp(
                float(normalized["wMom"]) * z_momentum[code]
                + float(normalized["wLowVol"]) * z_low_volatility[code]
                + float(normalized["wLiq"]) * z_liquidity[code]
            ),
            "confidence": min(
                1.0,
                abs(
                    float(normalized["wMom"]) * z_momentum[code]
                    + float(normalized["wLowVol"]) * z_low_volatility[code]
                    + float(normalized["wLiq"]) * z_liquidity[code]
                )
                / 3,
            ),
            "reason": (
                f"momZ={z_momentum[code]:.4f}, "
                f"lowVolZ={z_low_volatility[code]:.4f}, "
                f"liqZ={z_liquidity[code]:.4f}"
            ),
        }
        for code in momentum
    ]


def generate_builtin_signals(
    builtin_type: str,
    params: dict[str, Any],
    *,
    bars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    _, normalized = validate_params(builtin_type, params)
    if builtin_type == "composite_mf":
        return {
            "schemaVersion": 1,
            "protocolVersion": PROTOCOL_VERSION,
            "signals": _composite_signals(normalized, bars),
        }
    signals: list[dict[str, Any]] = []
    for raw_code, rows in bars.items():
        code = normalize_a_share_code(raw_code)
        values = _closes(rows)
        score: float | None = None
        reason = ""
        if builtin_type == "dual_ma":
            fast = int(normalized["fast"])
            slow = int(normalized["slow"])
            if len(values) >= slow:
                fast_ma = sum(values[-fast:]) / fast
                slow_ma = sum(values[-slow:]) / slow
                score = _clamp((fast_ma / slow_ma - 1) * 20)
                reason = f"fastMA={fast_ma:.4f}, slowMA={slow_ma:.4f}"
        elif builtin_type == "rsi":
            period = int(normalized["period"])
            if len(values) >= period + 1:
                value = _rsi(values, period)
                low = float(normalized["low"])
                high = float(normalized["high"])
                if value < low:
                    score = _clamp((low - value) / max(low, 1))
                elif value > high:
                    score = -_clamp((value - high) / max(100 - high, 1))
                else:
                    score = 0.0
                reason = f"RSI={value:.4f}"
        elif builtin_type == "boll":
            period = int(normalized["period"])
            if len(values) >= period:
                window = values[-period:]
                mean = sum(window) / period
                deviation = (
                    sum((value - mean) ** 2 for value in window) / period
                ) ** 0.5
                zscore = (window[-1] - mean) / deviation if deviation else 0.0
                score = _clamp(-zscore / max(float(normalized["k"]), 0.01))
                reason = f"bollZ={zscore:.4f}"
        elif builtin_type == "momentum":
            lookback = int(normalized["lookback"])
            if len(values) >= lookback + 1:
                momentum = values[-1] / values[-lookback - 1] - 1
                score = _clamp(momentum * 10)
                reason = f"momentum={momentum:.6f}"
        elif builtin_type == "donchian_breakout":
            channel = int(normalized["channel"])
            highs = [
                float(row["high"])
                for row in rows[-channel - 1 :]
                if isinstance(row.get("high"), (int, float))
            ]
            lows = [
                float(row["low"])
                for row in rows[-channel - 1 :]
                if isinstance(row.get("low"), (int, float))
            ]
            if min(len(values), len(highs), len(lows)) >= channel + 1:
                upper = max(highs[:-1])
                lower = min(lows[:-1])
                width = max(upper - lower, 1e-12)
                score = _clamp((values[-1] - upper) / width)
                reason = f"upper={upper:.4f}, lower={lower:.4f}"
        elif builtin_type == "xs_momentum":
            lookback = int(normalized["lookback"])
            if len(values) >= lookback + 1:
                momentum = values[-1] / values[-lookback - 1] - 1
                score = _clamp(momentum * 10)
                reason = f"xsMomentum={momentum:.6f}"
        elif builtin_type == "zscore_reversion":
            period = int(normalized["period"])
            if len(values) >= period:
                window = values[-period:]
                mean = sum(window) / period
                std = (
                    sum((value - mean) ** 2 for value in window) / period
                ) ** 0.5
                zscore = (window[-1] - mean) / std if std else 0.0
                score = _clamp(-zscore / max(abs(float(normalized["entryZ"])), 0.01))
                reason = f"zscore={zscore:.4f}"
        if score is None:
            continue
        signals.append(
            {
                "code": code,
                "score": score,
                "confidence": abs(score),
                "reason": reason,
            }
        )
    return {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "signals": signals,
    }


def generate_signals(
    *,
    definition_type: str,
    builtin_type: str | None,
    params: dict[str, Any],
    source_code: str | None,
    context: dict[str, Any],
    bars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if definition_type == "builtin" and builtin_type:
        return generate_builtin_signals(builtin_type, params, bars=bars)
    if definition_type == "custom_python" and source_code:
        custom_context = {**context, "params": params}
        return run_source(source_code, context=custom_context, bars=bars)
    raise ValueError("策略定义不完整")
