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


def generate_builtin_signals(
    builtin_type: str,
    params: dict[str, Any],
    *,
    bars: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    _, normalized = validate_params(builtin_type, params)
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
