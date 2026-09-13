"""Deterministic portfolio/risk officer for M3 strategy proposals."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MAX_GROSS_EXPOSURE = 2.0
MAX_EQUITY = 200_000.0
MAX_SINGLE_NAME = 0.20
MAX_INDUSTRY = 0.30
MAX_STRATEGY_RISK = 0.25
MAX_PREDICTED_DAILY_LOSS = 0.02

_REGIME_MULTIPLIERS = {
    "bull": {
        "trend_following": 1.2,
        "momentum": 1.2,
        "mean_reversion": 0.7,
        "multi_factor": 1.0,
        "event": 1.0,
    },
    "bear": {
        "trend_following": 0.6,
        "momentum": 0.5,
        "mean_reversion": 0.8,
        "multi_factor": 1.1,
        "event": 0.7,
    },
    "range": {
        "trend_following": 0.7,
        "momentum": 0.7,
        "mean_reversion": 1.2,
        "multi_factor": 1.0,
        "event": 0.9,
    },
    "risk_off": {
        "trend_following": 0.25,
        "momentum": 0.25,
        "mean_reversion": 0.25,
        "multi_factor": 0.25,
        "event": 0.25,
    },
}


@dataclass(frozen=True)
class StrategyProposal:
    strategy_id: str
    category: str
    confidence: float
    target_weights: dict[str, float]


def _scale(weights: dict[str, float], limit: float) -> dict[str, float]:
    total = sum(abs(value) for value in weights.values())
    if total <= limit or total == 0:
        return weights
    factor = limit / total
    return {code: value * factor for code, value in weights.items()}


def allocate_portfolio(
    *,
    proposals: list[StrategyProposal],
    regime: str,
    equity: float,
    industries: dict[str, str],
    predicted_loss_rates: dict[str, float],
    current_weights: dict[str, float] | None = None,
    drawdown: float = 0.0,
    max_gross_exposure: float = MAX_GROSS_EXPOSURE,
) -> dict[str, Any]:
    if regime not in _REGIME_MULTIPLIERS:
        raise ValueError("未知市场状态")
    if equity <= 0 or not math.isfinite(equity) or equity > MAX_EQUITY:
        raise ValueError("equity 必须是正的有限数且不超过 20 万")
    if not 0 <= drawdown <= 1:
        raise ValueError("drawdown 必须在 [0,1]")
    if not 0 < max_gross_exposure <= MAX_GROSS_EXPOSURE:
        raise ValueError("总敞口上限必须在 (0,2]")
    current = current_weights or {}
    if drawdown >= 0.20:
        return {
            "weights": {code: 0.0 for code in current},
            "amounts": {code: 0.0 for code in current},
            "grossExposure": 0.0,
            "predictedDailyLoss": 0.0,
            "riskState": "force_reduce",
            "reasons": ["drawdown_at_or_above_20pct"],
        }
    combined: dict[str, float] = {}
    strategy_audit: list[dict[str, Any]] = []
    sleeves: list[tuple[StrategyProposal, float, dict[str, float]]] = []
    for proposal in proposals:
        if not 0 <= proposal.confidence <= 1:
            raise ValueError("策略置信度必须在 [0,1]")
        multiplier = _REGIME_MULTIPLIERS[regime].get(
            proposal.category, 0.5
        )
        raw = {
            code: max(0.0, float(weight))
            * proposal.confidence
            * multiplier
            for code, weight in proposal.target_weights.items()
            if math.isfinite(float(weight))
        }
        bounded = _scale(raw, MAX_STRATEGY_RISK)
        sleeves.append((proposal, multiplier, bounded))
    category_gross: dict[str, float] = {}
    for proposal, _, sleeve in sleeves:
        category_gross[proposal.category] = (
            category_gross.get(proposal.category, 0.0)
            + sum(sleeve.values())
        )
    for proposal, multiplier, sleeve in sleeves:
        category_factor = min(
            1.0,
            MAX_STRATEGY_RISK
            / max(category_gross[proposal.category], 1e-12),
        )
        bounded = {
            code: weight * category_factor
            for code, weight in sleeve.items()
        }
        strategy_audit.append(
            {
                "strategyId": proposal.strategy_id,
                "category": proposal.category,
                "regimeMultiplier": multiplier,
                "grossContribution": sum(bounded.values()),
                "categoryPoolFactor": category_factor,
            }
        )
        for code, weight in bounded.items():
            combined[code] = combined.get(code, 0.0) + weight
    combined = {
        code: min(weight, MAX_SINGLE_NAME)
        for code, weight in combined.items()
    }
    missing_industries = sorted(set(combined) - set(industries))
    if missing_industries:
        raise ValueError(
            f"缺少 {len(missing_industries)} 个标的的行业归属"
        )
    by_industry: dict[str, list[str]] = {}
    for code in combined:
        by_industry.setdefault(industries[code], []).append(
            code
        )
    for codes in by_industry.values():
        total = sum(combined[code] for code in codes)
        if total > MAX_INDUSTRY:
            factor = MAX_INDUSTRY / total
            for code in codes:
                combined[code] *= factor
    combined = _scale(combined, max_gross_exposure)
    missing_losses = sorted(set(combined) - set(predicted_loss_rates))
    if missing_losses:
        raise ValueError(
            f"缺少 {len(missing_losses)} 个标的的预测亏损率"
        )
    if any(
        not math.isfinite(predicted_loss_rates[code])
        or predicted_loss_rates[code] < 0
        for code in combined
    ):
        raise ValueError("预测亏损率必须是非负有限数")
    predicted_loss = sum(
        abs(weight) * max(0.0, predicted_loss_rates[code])
        for code, weight in combined.items()
    )
    if predicted_loss > MAX_PREDICTED_DAILY_LOSS:
        combined = _scale(
            combined,
            sum(combined.values())
            * MAX_PREDICTED_DAILY_LOSS
            / predicted_loss,
        )
        predicted_loss = MAX_PREDICTED_DAILY_LOSS
    risk_state = "normal"
    reasons: list[str] = []
    if drawdown >= 0.18:
        risk_state = "no_new_positions"
        reasons.append("drawdown_at_or_above_18pct")
        combined = {
            code: min(weight, max(current.get(code, 0.0), 0.0))
            for code, weight in combined.items()
        }
    elif drawdown >= 0.15:
        risk_state = "warning"
        reasons.append("drawdown_at_or_above_15pct")
    gross = sum(combined.values())
    predicted_loss = sum(
        weight * max(0.0, predicted_loss_rates[code])
        for code, weight in combined.items()
    )
    predicted_loss = min(predicted_loss, MAX_PREDICTED_DAILY_LOSS)
    return {
        "weights": combined,
        "amounts": {
            code: round(weight * equity, 2)
            for code, weight in combined.items()
        },
        "grossExposure": gross,
        "predictedDailyLoss": predicted_loss,
        "riskState": risk_state,
        "reasons": reasons,
        "strategyAudit": strategy_audit,
        "limits": {
            "grossExposure": max_gross_exposure,
            "singleName": MAX_SINGLE_NAME,
            "industry": MAX_INDUSTRY,
            "strategyRisk": MAX_STRATEGY_RISK,
            "predictedDailyLoss": MAX_PREDICTED_DAILY_LOSS,
        },
    }
