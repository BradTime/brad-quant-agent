"""Prediction calibration and M3 promotion gates."""

from __future__ import annotations

from typing import Any


def _same_length(*values: list) -> None:
    lengths = {len(value) for value in values}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise ValueError("评测数组必须非空且长度一致")


def balanced_accuracy(labels: list[int], probabilities: list[float]) -> float:
    _same_length(labels, probabilities)
    positives = [index for index, label in enumerate(labels) if label == 1]
    negatives = [index for index, label in enumerate(labels) if label == 0]
    if not positives or not negatives:
        raise ValueError("方向评测必须同时包含上涨和下跌样本")
    sensitivity = sum(probabilities[index] >= 0.5 for index in positives) / len(
        positives
    )
    specificity = sum(probabilities[index] < 0.5 for index in negatives) / len(
        negatives
    )
    return (sensitivity + specificity) / 2


def brier_score(labels: list[int], probabilities: list[float]) -> float:
    _same_length(labels, probabilities)
    if any(not 0 <= probability <= 1 for probability in probabilities):
        raise ValueError("概率必须在 [0,1]")
    return sum(
        (probability - label) ** 2
        for label, probability in zip(labels, probabilities, strict=True)
    ) / len(labels)


def calibration_error(
    labels: list[int],
    probabilities: list[float],
    *,
    bins: int = 10,
) -> float:
    _same_length(labels, probabilities)
    if bins < 2:
        raise ValueError("校准分箱至少为 2")
    total = len(labels)
    error = 0.0
    for bucket in range(bins):
        lower = bucket / bins
        upper = (bucket + 1) / bins
        indexes = [
            index
            for index, probability in enumerate(probabilities)
            if lower <= probability < upper
            or (bucket == bins - 1 and probability == 1)
        ]
        if not indexes:
            continue
        confidence = sum(probabilities[index] for index in indexes) / len(indexes)
        frequency = sum(labels[index] for index in indexes) / len(indexes)
        error += len(indexes) / total * abs(confidence - frequency)
    return error


def interval_coverage(
    actual: list[float],
    lower: list[float],
    upper: list[float],
) -> float:
    _same_length(actual, lower, upper)
    if any(low > high for low, high in zip(lower, upper, strict=True)):
        raise ValueError("收益区间下界不得大于上界")
    return sum(
        low <= value <= high
        for value, low, high in zip(actual, lower, upper, strict=True)
    ) / len(actual)


def evaluate_predictions(
    *,
    labels: list[int],
    probabilities: list[float],
    returns: list[float],
    lower: list[float],
    upper: list[float],
) -> dict[str, Any]:
    _same_length(labels, probabilities, returns, lower, upper)
    metrics = {
        "balancedAccuracy": balanced_accuracy(labels, probabilities),
        "brierScore": brier_score(labels, probabilities),
        "expectedCalibrationError": calibration_error(
            labels, probabilities
        ),
        "intervalCoverage": interval_coverage(returns, lower, upper),
        "samples": len(labels),
    }
    reasons: list[str] = []
    if metrics["samples"] < 100:
        reasons.append("samples_below_100")
    if metrics["balancedAccuracy"] < 0.53:
        reasons.append("balanced_accuracy_below_53pct")
    if metrics["expectedCalibrationError"] > 0.1:
        reasons.append("calibration_error_above_10pct")
    if not 0.75 <= metrics["intervalCoverage"] <= 0.85:
        reasons.append("interval_coverage_outside_75_85pct")
    return {
        **metrics,
        "passed": not reasons,
        "promotionEligible": False,
        "reasons": reasons,
    }
