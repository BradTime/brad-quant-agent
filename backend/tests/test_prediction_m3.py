from datetime import date, timedelta

import pytest

from app.backtest.data import Bar
from app.prediction.artifacts import save_model_bundle, verify_model_bundle
from app.prediction.evaluation import evaluate_predictions
from app.prediction.features import PredictionExample, build_daily_examples
from app.prediction.modeling import FEATURE_ORDER, _models, train_prediction_model
from app.prediction.portfolio import StrategyProposal, allocate_portfolio
from app.prediction.regime import classify_market_regime
from app.prediction.temporal import purged_walk_forward


def _bars(count: int = 420) -> list[Bar]:
    start = date(2024, 1, 1)
    return [
        Bar(
            code="600000.SH",
            date=start + timedelta(days=index),
            open=10 + index * 0.01,
            high=10.2 + index * 0.01,
            low=9.8 + index * 0.01,
            close=10.1 + index * 0.01,
            volume=1_000_000 + index,
            amount=(1_000_000 + index) * (10 + index * 0.01),
        )
        for index in range(count)
    ]


def test_daily_features_use_signal_data_and_next_open_to_close_label():
    bars = _bars(30)
    examples = build_daily_examples({"600000.SH": bars})
    first = examples[0]
    signal_index = next(
        index for index, bar in enumerate(bars) if bar.date == first.signal_date
    )
    expected = bars[signal_index + 1].close / bars[signal_index + 1].open - 1
    assert first.next_return == expected
    assert first.features["return1"] == (
        bars[signal_index].close / bars[signal_index - 1].close - 1
    )
    assert first.label_date > first.signal_date


def test_daily_features_never_label_across_missing_market_sessions():
    bars = _bars(30)
    bars[21] = Bar(
        **{
            **bars[21].__dict__,
            "date": bars[21].date + timedelta(days=10),
        }
    )
    gap_label = bars[21].date
    examples = build_daily_examples({"600000.SH": bars})
    assert all(row.label_date != gap_label for row in examples)


def test_purged_walk_forward_has_embargo_and_no_date_overlap():
    examples = build_daily_examples({"600000.SH": _bars()})
    folds = purged_walk_forward(
        examples,
        minimum_train_dates=150,
        validation_dates=40,
        embargo_dates=2,
        max_folds=2,
    )
    assert folds
    for fold in folds:
        train_dates = {row.signal_date for row in fold.train}
        validation_dates = {row.signal_date for row in fold.validation}
        assert train_dates.isdisjoint(validation_dates)
        assert (fold.validation_start - fold.train_end).days >= 2


def test_prediction_release_metrics_require_calibration_and_80pct_coverage():
    labels = [0, 1] * 50
    probabilities = [0.0, 1.0] * 50
    returns = [-0.01, 0.01] * 50
    lower = [-0.02] * 80 + [0.0] * 20
    upper = [0.02] * 80 + [0.005] * 20
    report = evaluate_predictions(
        labels=labels,
        probabilities=probabilities,
        returns=returns,
        lower=lower,
        upper=upper,
    )
    assert report["balancedAccuracy"] == 1
    assert report["brierScore"] == 0
    assert report["intervalCoverage"] == 0.8
    assert report["passed"]


def test_rule_regime_is_auditable_and_fails_on_short_history():
    with pytest.raises(ValueError, match="60"):
        classify_market_regime(index_closes=[100] * 59, market_breadth=0.5)
    bull = classify_market_regime(
        index_closes=[100 + index for index in range(60)],
        market_breadth=0.7,
    )
    assert bull["regime"] == "bull"
    assert bull["rulesVersion"] == "regime-rules-v1"


def test_portfolio_risk_officer_enforces_allocation_and_drawdown_limits():
    proposals = [
        StrategyProposal(
            strategy_id="trend",
            category="trend_following",
            confidence=1.0,
            target_weights={"A": 1.0, "B": 1.0},
        ),
        StrategyProposal(
            strategy_id="factor",
            category="multi_factor",
            confidence=1.0,
            target_weights={"A": 0.8, "C": 0.8},
        ),
    ]
    result = allocate_portfolio(
        proposals=proposals,
        regime="bull",
        equity=200_000,
        industries={"A": "bank", "B": "bank", "C": "tech"},
        predicted_loss_rates={"A": 0.1, "B": 0.1, "C": 0.1},
    )
    assert max(result["weights"].values()) <= 0.20
    assert result["weights"]["A"] + result["weights"]["B"] <= 0.30
    assert result["predictedDailyLoss"] <= 0.02
    stopped = allocate_portfolio(
        proposals=proposals,
        regime="bull",
        equity=200_000,
        industries={"A": "bank", "B": "bank", "C": "tech"},
        predicted_loss_rates={"A": 0.1, "B": 0.1, "C": 0.1},
        current_weights={"A": 0.1},
        drawdown=0.20,
    )
    assert stopped["riskState"] == "force_reduce"
    assert stopped["weights"] == {"A": 0.0}


def test_lightgbm_direction_and_quantile_adapter_is_bounded(
    tmp_path, monkeypatch
):
    start = date(2024, 1, 1)
    examples = [
        PredictionExample(
            code=f"CODE-{index % 5}",
            signal_date=start + timedelta(days=index // 5),
            label_date=start + timedelta(days=index // 5 + 1),
            features={
                field: ((index % 7) - 3) / 10 + position / 100
                for position, field in enumerate(FEATURE_ORDER)
            },
            next_return=0.01 if index % 2 else -0.01,
            next_up=index % 2,
        )
        for index in range(300)
    ]
    model = train_prediction_model(examples, provider="lightgbm", seed=7)
    predictions = model.predict(examples[-5:])
    assert len(predictions) == 5
    assert all(0 <= row["probabilityUp"] <= 1 for row in predictions)
    assert all(
        row["returnP10"] <= row["returnP50"] <= row["returnP90"]
        for row in predictions
    )
    classifier, quantiles = _models("xgboost", 7)
    assert classifier is not None and len(quantiles) == 3
    monkeypatch.setattr(
        "app.prediction.artifacts.settings.prediction_artifact_dir",
        str(tmp_path),
    )
    artifact = save_model_bundle(
        model,
        version="candidate-1",
        metrics={"passed": True},
        data_sha256="a" * 64,
    )
    verified = verify_model_bundle(
        artifact["artifactPath"],
        expected_sha256=artifact["modelSha256"],
        expected_manifest_sha256=artifact["manifestSha256"],
    )
    assert verified["version"] == "candidate-1"
    assert verified["promotionEligible"] is False
    manifest_path = artifact["manifestPath"]
    with open(manifest_path, "a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="manifest checksum"):
        verify_model_bundle(
            artifact["artifactPath"],
            expected_sha256=artifact["modelSha256"],
            expected_manifest_sha256=artifact["manifestSha256"],
        )
    with open(manifest_path, "rb+") as handle:
        handle.seek(-1, 2)
        handle.truncate()
    with open(artifact["artifactPath"], "ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_model_bundle(
            artifact["artifactPath"],
            expected_sha256=artifact["modelSha256"],
            expected_manifest_sha256=artifact["manifestSha256"],
        )


def test_correlated_strategy_category_shares_one_risk_pool():
    result = allocate_portfolio(
        proposals=[
            StrategyProposal(
                strategy_id="m1",
                category="momentum",
                confidence=1,
                target_weights={"A": 1},
            ),
            StrategyProposal(
                strategy_id="m2",
                category="momentum",
                confidence=1,
                target_weights={"B": 1},
            ),
        ],
        regime="bull",
        equity=200_000,
        industries={"A": "one", "B": "two"},
        predicted_loss_rates={"A": 0.01, "B": 0.01},
    )
    contribution = sum(
        row["grossContribution"] for row in result["strategyAudit"]
    )
    assert contribution <= 0.25
