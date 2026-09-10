"""Pure, deterministic actors for the M4 decision chain."""

from __future__ import annotations

import math
from typing import Any

PROTOCOL_VERSION = "decision-chain-v1"
MAX_CROSS_EXAMINATION_ROUNDS = 2


def _prediction_map(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    predictions = inputs.get("predictions")
    if not isinstance(predictions, list) or not predictions:
        raise ValueError("研究输入缺少 Champion 预测")
    result = {}
    for prediction in predictions:
        code = str(prediction.get("code") or "")
        interval = prediction.get("returnInterval80") or {}
        values = (
            prediction.get("probabilityUp"),
            interval.get("low"),
            interval.get("median"),
            interval.get("high"),
        )
        if (
            not code
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in values
            )
        ):
            raise ValueError("Champion 预测证据不完整")
        probability_up = float(prediction["probabilityUp"])
        low = float(interval["low"])
        median = float(interval["median"])
        high = float(interval["high"])
        if not 0 <= probability_up <= 1:
            raise ValueError("Champion 方向概率越界")
        if not low <= median <= high:
            raise ValueError("Champion 收益区间顺序无效")
        if code in result:
            raise ValueError("Champion 预测标的重复")
        result[code] = prediction
    return result


def _validate_allocation(
    inputs: dict[str, Any],
    allocation: dict[str, Any],
    predictions: dict[str, dict[str, Any]],
) -> None:
    if (
        allocation.get("authoritative") is not True
        or allocation.get("executionApproved") is not False
    ):
        raise ValueError("组合证据不是未执行的服务端权威结果")
    risk_state = allocation.get("riskState")
    if risk_state not in {
        "normal",
        "warning",
        "no_new_positions",
        "force_reduce",
    }:
        raise ValueError("组合风险状态无效")
    weights = allocation.get("weights")
    amounts = allocation.get("amounts")
    if not isinstance(weights, dict) or not isinstance(amounts, dict):
        raise ValueError("组合权重或金额缺失")
    if set(weights) - set(predictions) or set(amounts) != set(weights):
        raise ValueError("组合标的与 Champion 预测不一致")
    capital_value = (inputs.get("riskProfile") or {}).get("capitalLimit", 0)
    leverage_value = (inputs.get("riskProfile") or {}).get(
        "leverageLimit", -1
    )
    if (
        isinstance(capital_value, bool)
        or not isinstance(capital_value, (int, float))
    ):
        raise ValueError("服务端风险资金上限无效")
    if (
        isinstance(leverage_value, bool)
        or not isinstance(leverage_value, (int, float))
    ):
        raise ValueError("服务端杠杆资金上限无效")
    capital = float(capital_value)
    leverage = float(leverage_value)
    if not math.isfinite(capital) or not 0 < capital <= 200_000:
        raise ValueError("服务端风险资金上限无效")
    if (
        not math.isfinite(leverage)
        or not 0 <= leverage <= 200_000
    ):
        raise ValueError("服务端杠杆资金上限无效")
    for code, weight_value in weights.items():
        amount_value = amounts[code]
        if (
            isinstance(weight_value, bool)
            or isinstance(amount_value, bool)
            or not isinstance(weight_value, (int, float))
            or not isinstance(amount_value, (int, float))
            or not math.isfinite(float(weight_value))
            or not math.isfinite(float(amount_value))
        ):
            raise ValueError("组合权重或金额不是有限数")
        weight = float(weight_value)
        amount = float(amount_value)
        if not 0 <= weight <= 0.20 or amount < 0:
            raise ValueError("组合权重或金额越界")
        if abs(amount - round(weight * capital, 2)) > 0.011:
            raise ValueError("组合金额与权重不一致")
    gross = allocation.get("grossExposure")
    predicted_loss = allocation.get("predictedDailyLoss")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in (gross, predicted_loss)
    ):
        raise ValueError("组合风险指标无效")
    if abs(float(gross) - sum(float(v) for v in weights.values())) > 1e-9:
        raise ValueError("组合总敞口与权重不一致")
    max_gross = 1 + leverage / capital
    if float(gross) > max_gross + 1e-9:
        raise ValueError("组合总敞口超过服务端杠杆上限")
    if not 0 <= float(predicted_loss) <= 0.02:
        raise ValueError("组合预测日损失越界")
    industries = inputs.get("industries")
    if not isinstance(industries, dict) or set(weights) - set(industries):
        raise ValueError("组合缺少服务端 PIT 行业")
    industry_weights: dict[str, float] = {}
    for code, weight in weights.items():
        industry = str(industries[code])
        industry_weights[industry] = (
            industry_weights.get(industry, 0.0) + float(weight)
        )
    if any(weight > 0.30 + 1e-9 for weight in industry_weights.values()):
        raise ValueError("组合行业敞口超过 30%")
    limits = allocation.get("limits")
    if risk_state != "force_reduce":
        expected_limits = {
            "grossExposure": max_gross,
            "singleName": 0.20,
            "industry": 0.30,
            "strategyRisk": 0.25,
            "predictedDailyLoss": 0.02,
        }
        if not isinstance(limits, dict) or any(
            key not in limits
            or not isinstance(limits[key], (int, float))
            or isinstance(limits[key], bool)
            or abs(float(limits[key]) - expected) > 1e-9
            for key, expected in expected_limits.items()
        ):
            raise ValueError("组合风险限制证据不一致")


def researcher(
    inputs: dict[str, Any],
    allocation: dict[str, Any],
) -> dict[str, Any]:
    predictions = _prediction_map(inputs)
    _validate_allocation(inputs, allocation, predictions)
    weights = allocation.get("weights") or {}
    amounts = allocation.get("amounts") or {}
    claims = []
    for code, prediction in sorted(predictions.items()):
        interval = prediction["returnInterval80"]
        probability_up = float(prediction["probabilityUp"])
        claims.append(
            {
                "code": code,
                "direction": "up" if probability_up > 0.5 else "down",
                "probabilityUp": probability_up,
                "probabilityDown": 1 - probability_up,
                "returnInterval80": interval,
                "targetWeight": float(weights.get(code, 0.0)),
                "targetAmount": float(amounts.get(code, 0.0)),
                "stopLossRate": min(
                    0.0, max(-0.10, float(interval["low"]))
                ),
                "takeProfitRate": min(
                    0.20, max(0.0, float(interval["high"]))
                ),
                "maxHoldingSessions": 5,
                "noTradeConditions": [
                    "probability_up_at_or_below_50pct",
                    "median_return_not_positive",
                    "risk_officer_veto",
                    "stale_or_missing_server_evidence",
                ],
                "evidenceRefs": {
                    "featureSha256": prediction.get("featureSha256"),
                    "modelArtifactSha256": (
                        prediction.get("model") or {}
                    ).get("artifactSha256"),
                },
            }
        )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "role": "researcher",
        "claims": claims,
        "portfolioRiskState": allocation.get("riskState"),
        "predictedDailyLoss": allocation.get("predictedDailyLoss"),
        "evidencePolicy": "server_records_only",
    }


def contrarian_blind(inputs: dict[str, Any]) -> dict[str, Any]:
    """Review raw evidence without receiving the researcher's claims."""
    predictions = _prediction_map(inputs)
    regime = str((inputs.get("regime") or {}).get("regime") or "")
    reviews = []
    for code, prediction in sorted(predictions.items()):
        interval = prediction["returnInterval80"]
        probability_up = float(prediction["probabilityUp"])
        low = float(interval["low"])
        median = float(interval["median"])
        concerns = []
        if low < -0.02:
            concerns.append("downside_tail_below_2pct")
        if regime == "risk_off":
            concerns.append("market_regime_risk_off")
        if probability_up < 0.55:
            concerns.append("direction_edge_below_55pct")
        if low <= 0 <= float(interval["high"]):
            concerns.append("return_interval_crosses_zero")
        alternative_weight = (
            min(0.10, max(0.0, (probability_up - 0.55) * 0.5))
            if not concerns
            else 0.0
        )
        reviews.append(
            {
                "code": code,
                "independentDirection": (
                    "avoid"
                    if concerns
                    else ("up" if median > 0 else "down")
                ),
                "conservativeExpectedReturn": low,
                "alternativeWeight": alternative_weight,
                "concerns": concerns,
                "alternatives": [
                    "no_trade",
                    "wait_for_new_session_evidence",
                    "use_lower_correlated_candidate",
                ],
                "evidenceRefs": {
                    "featureSha256": prediction.get("featureSha256"),
                    "universeMembershipSha256": (
                        inputs.get("regime") or {}
                    ).get("universeMembershipSha256"),
                },
            }
        )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "role": "contrarian",
        "blindReview": True,
        "receivedResearcherClaim": False,
        "reviews": reviews,
    }


def cross_examine(
    research: dict[str, Any],
    contrarian: dict[str, Any],
    *,
    round_number: int,
) -> dict[str, Any]:
    if round_number not in {1, 2}:
        raise ValueError("交叉质询只允许两轮")
    claims = {claim["code"]: claim for claim in research["claims"]}
    reviews = {
        review["code"]: review for review in contrarian["reviews"]
    }
    exchanges = []
    for code in sorted(set(claims) | set(reviews)):
        claim = claims.get(code)
        review = reviews.get(code)
        if claim is None or review is None:
            exchanges.append(
                {
                    "code": code,
                    "resolved": False,
                    "finding": "evidence_set_mismatch",
                    "evidenceMismatch": True,
                }
            )
            continue
        review_direction = review["independentDirection"]
        direction_conflict = (
            review_direction == "avoid"
            or (claim["direction"] == "up" and review_direction == "down")
            or (claim["direction"] == "down" and review_direction == "up")
        )
        evidence_mismatch = (
            not claim["evidenceRefs"].get("featureSha256")
            or claim["evidenceRefs"].get("featureSha256")
            != review["evidenceRefs"].get("featureSha256")
        )
        return_gap = abs(
            float(claim["returnInterval80"]["median"])
            - float(review["conservativeExpectedReturn"])
        )
        weight_gap = abs(
            float(claim["targetWeight"])
            - float(review["alternativeWeight"])
        )
        exchanges.append(
            {
                "code": code,
                "directionConflict": direction_conflict,
                "returnEstimateGap": return_gap,
                "positionGap": weight_gap,
                "evidenceMismatch": evidence_mismatch,
                "researcherResponse": (
                    "model_interval_and_calibration_evidence_retained"
                    if round_number == 1
                    else "risk_limits_and_no_trade_conditions_accept_tail_risk"
                ),
                "contrarianResponse": (
                    "request_tail_and_regime_stress_test"
                    if round_number == 1
                    else "maintain_no_trade_alternative"
                ),
                "resolved": not (
                    direction_conflict
                    or evidence_mismatch
                    or return_gap > 0.02
                    or weight_gap > 0.10
                ),
            }
        )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "role": "cross_examination",
        "round": round_number,
        "exchanges": exchanges,
    }


def investment_committee(
    research: dict[str, Any],
    contrarian: dict[str, Any],
    examinations: list[dict[str, Any]],
) -> dict[str, Any]:
    if (
        len(examinations) != MAX_CROSS_EXAMINATION_ROUNDS
        or {item.get("round") for item in examinations} != {1, 2}
        or any(
            item.get("role") != "cross_examination"
            or item.get("protocolVersion") != PROTOCOL_VERSION
            for item in examinations
        )
    ):
        raise ValueError("投资委员会必须收到完整两轮质询")
    claims = {claim["code"]: claim for claim in research["claims"]}
    reviews = {
        review["code"]: review for review in contrarian["reviews"]
    }
    decisions = []
    severe_reasons: list[str] = []
    for code, claim in sorted(claims.items()):
        review = reviews.get(code)
        if review is None:
            severe_reasons.append(f"{code}:evidence_set_mismatch")
            decisions.append(
                {
                    "code": code,
                    "status": "no_trade",
                    "confidence": 0.0,
                    "acceptedResearchEvidence": claim["evidenceRefs"],
                    "contrarianConcerns": ["review_missing"],
                    "contrarianConcernDisposition": [
                        {
                            "concern": "review_missing",
                            "disposition": "adopted",
                            "reason": "blind_review_required",
                        }
                    ],
                }
            )
            continue
        direction_edge = max(
            0.0, (float(claim["probabilityUp"]) - 0.5) * 2
        )
        return_edge = min(
            1.0,
            max(0.0, float(claim["returnInterval80"]["median"]) / 0.03),
        )
        position_support = min(
            1.0, float(claim["targetWeight"]) / 0.20
        )
        confidence = (
            0.40 * direction_edge
            + 0.30 * return_edge
            + 0.30 * position_support
        )
        conflicts = [
            exchange
            for examination in examinations
            for exchange in examination["exchanges"]
            if exchange["code"] == code and not exchange["resolved"]
        ]
        if conflicts:
            confidence *= 0.80
        status = (
            "approved_candidate"
            if confidence >= 0.60 and claim["targetWeight"] > 0
            else "no_trade"
        )
        if confidence < 0.60:
            severe_reasons.append(f"{code}:committee_confidence_below_60pct")
        for conflict in conflicts:
            if conflict.get("directionConflict"):
                severe_reasons.append(f"{code}:direction_conflict")
            if conflict.get("evidenceMismatch"):
                severe_reasons.append(f"{code}:evidence_set_mismatch")
            if float(conflict.get("returnEstimateGap", 0)) > 0.02:
                severe_reasons.append(f"{code}:return_gap_above_2pct")
            if float(conflict.get("positionGap", 0)) > 0.10:
                severe_reasons.append(f"{code}:position_gap_above_10pct")
        dispositions = []
        for concern in review["concerns"]:
            if status == "no_trade":
                dispositions.append(
                    {
                        "concern": concern,
                        "disposition": "adopted",
                        "reason": "committee_confidence_or_target_gate",
                    }
                )
            else:
                reason_by_concern = {
                    "downside_tail_below_2pct": (
                        "authoritative_predicted_loss_cap_and_stop_boundary"
                    ),
                    "market_regime_risk_off": (
                        "authoritative_regime_multiplier_reduced_target"
                    ),
                    "direction_edge_below_55pct": (
                        "aggregate_deterministic_score_above_60pct"
                    ),
                    "return_interval_crosses_zero": (
                        "positive_median_with_bounded_target_and_no_trade_gate"
                    ),
                }
                dispositions.append(
                    {
                        "concern": concern,
                        "disposition": "not_adopted",
                        "reason": reason_by_concern.get(
                            concern, "unrecognized_concern_requires_no_trade"
                        ),
                    }
                )
                if concern not in reason_by_concern:
                    status = "no_trade"
        decisions.append(
            {
                "code": code,
                "status": status,
                "confidence": confidence,
                "acceptedResearchEvidence": claim["evidenceRefs"],
                "contrarianConcerns": review["concerns"],
                "contrarianConcernDisposition": dispositions,
            }
        )
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "role": "investment_committee",
        "decisions": decisions,
        "severeDisagreement": bool(severe_reasons),
        "severeDisagreementReasons": sorted(set(severe_reasons)),
    }


def risk_officer(
    committee: dict[str, Any],
    allocation: dict[str, Any],
) -> dict[str, Any]:
    risk_state = str(allocation.get("riskState") or "")
    veto_reasons = []
    if risk_state not in {
        "normal",
        "warning",
        "no_new_positions",
        "force_reduce",
    }:
        veto_reasons.append("portfolio_risk_state:invalid")
    elif risk_state in {"force_reduce", "no_new_positions"}:
        veto_reasons.append(f"portfolio_risk_state:{risk_state}")
    approved_codes = [
        decision["code"]
        for decision in committee["decisions"]
        if decision["status"] == "approved_candidate"
    ]
    if not approved_codes:
        veto_reasons.append("committee_approved_no_candidates")
    weights = allocation.get("weights")
    if not isinstance(weights, dict):
        veto_reasons.append("authoritative_allocation_missing")
        weights = {}
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "role": "risk_officer",
        "veto": bool(veto_reasons),
        "vetoReasons": veto_reasons,
        "approvedCandidateWeights": (
            {
                code: float(weights.get(code, 0.0))
                for code in approved_codes
            }
            if not veto_reasons
            else {}
        ),
        "executionApproved": False,
        "notice": "风险官仅批准研究候选；M4 不创建或提交订单",
    }
