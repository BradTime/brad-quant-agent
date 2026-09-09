"""Out-of-fold evaluation required before a model can be registered/promoted."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.prediction.evaluation import evaluate_predictions
from app.prediction.features import PredictionExample
from app.prediction.modeling import ModelProvider, train_prediction_model
from app.prediction.temporal import purged_walk_forward

REQUIRED_REGIMES = frozenset({"bull", "bear", "range", "risk_off"})


def evaluate_walk_forward(
    examples: list[PredictionExample],
    *,
    regime_by_date: dict[date, str],
    provider: ModelProvider = "lightgbm",
    minimum_train_dates: int = 252,
    validation_dates: int = 63,
    embargo_dates: int = 5,
    max_folds: int = 5,
) -> dict[str, Any]:
    folds = purged_walk_forward(
        examples,
        minimum_train_dates=minimum_train_dates,
        validation_dates=validation_dates,
        embargo_dates=embargo_dates,
        max_folds=max_folds,
    )
    if len(folds) < 3:
        raise ValueError("模型晋级至少需要 3 个 Purged Walk-Forward 折")
    all_rows: list[PredictionExample] = []
    all_predictions: list[dict[str, float]] = []
    fold_reports: list[dict[str, Any]] = []
    for index, fold in enumerate(folds):
        model = train_prediction_model(
            list(fold.train),
            provider=provider,
            seed=index,
        )
        rows = list(fold.validation)
        predictions = model.predict(rows)
        report = evaluate_predictions(
            labels=[row.next_up for row in rows],
            probabilities=[
                prediction["probabilityUp"] for prediction in predictions
            ],
            returns=[row.next_return for row in rows],
            lower=[prediction["returnP10"] for prediction in predictions],
            upper=[prediction["returnP90"] for prediction in predictions],
        )
        fold_reports.append(
            {
                **report,
                "fold": index + 1,
                "trainEnd": fold.train_end.isoformat(),
                "validationStart": fold.validation_start.isoformat(),
                "validationEnd": fold.validation_end.isoformat(),
            }
        )
        all_rows.extend(rows)
        all_predictions.extend(predictions)
    aggregate = evaluate_predictions(
        labels=[row.next_up for row in all_rows],
        probabilities=[
            prediction["probabilityUp"] for prediction in all_predictions
        ],
        returns=[row.next_return for row in all_rows],
        lower=[prediction["returnP10"] for prediction in all_predictions],
        upper=[prediction["returnP90"] for prediction in all_predictions],
    )
    by_regime: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(all_rows):
        regime = regime_by_date.get(row.signal_date)
        if regime in REQUIRED_REGIMES:
            by_regime[regime].append(index)
    regime_reports: dict[str, dict[str, Any]] = {}
    for regime in sorted(REQUIRED_REGIMES):
        indexes = by_regime.get(regime, [])
        if len(indexes) < 100:
            regime_reports[regime] = {
                "passed": False,
                "samples": len(indexes),
                "reasons": ["regime_samples_below_100"],
            }
            continue
        regime_reports[regime] = evaluate_predictions(
            labels=[all_rows[index].next_up for index in indexes],
            probabilities=[
                all_predictions[index]["probabilityUp"]
                for index in indexes
            ],
            returns=[all_rows[index].next_return for index in indexes],
            lower=[
                all_predictions[index]["returnP10"] for index in indexes
            ],
            upper=[
                all_predictions[index]["returnP90"] for index in indexes
            ],
        )
    promotion_eligible = bool(
        aggregate["passed"]
        and all(report["passed"] for report in fold_reports)
        and all(
            report["passed"] for report in regime_reports.values()
        )
        and set(regime_reports) == REQUIRED_REGIMES
    )
    return {
        "provider": provider,
        "aggregate": aggregate,
        "folds": fold_reports,
        "regimes": regime_reports,
        "promotionEligible": promotion_eligible,
        "oosSamples": len(all_rows),
    }
