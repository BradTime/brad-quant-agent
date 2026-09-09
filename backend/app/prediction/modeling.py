"""LightGBM/XGBoost direction and quantile prediction adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from sklearn.isotonic import IsotonicRegression

from app.prediction.features import PredictionExample, PredictionFeature

ModelProvider = Literal["lightgbm", "xgboost"]
FEATURE_ORDER = (
    "return1",
    "return5",
    "return20",
    "volatility20",
    "range1",
    "amountZ20",
    "volumeZ20",
)


@dataclass
class IsotonicCalibrator:
    x: list[float]
    y: list[float]

    def predict(self, values) -> np.ndarray:
        return np.interp(values, self.x, self.y)


@dataclass
class TrainedPredictionModel:
    provider: ModelProvider
    classifier: Any
    calibrator: IsotonicCalibrator
    quantile_models: tuple[Any, Any, Any]

    def predict(self, examples: list[PredictionFeature]) -> list[dict[str, float]]:
        matrix = _matrix(examples)
        if hasattr(self.classifier, "predict_proba"):
            raw_probability = self.classifier.predict_proba(matrix)[:, 1]
        else:
            raw_probability = self.classifier.predict(matrix)
        probability = self.calibrator.predict(raw_probability)
        quantiles = [
            model.predict(matrix) for model in self.quantile_models
        ]
        results: list[dict[str, float]] = []
        for index, up_probability in enumerate(probability):
            ordered = sorted(float(values[index]) for values in quantiles)
            results.append(
                {
                    "probabilityUp": min(max(float(up_probability), 0.0), 1.0),
                    "returnP10": ordered[0],
                    "returnP50": ordered[1],
                    "returnP90": ordered[2],
                }
            )
        return results


def _matrix(examples: list[PredictionFeature]) -> np.ndarray:
    if not examples:
        raise ValueError("模型输入不能为空")
    return np.asarray(
        [
            [row.features[field] for field in FEATURE_ORDER]
            for row in examples
        ],
        dtype=np.float64,
    )


def _models(provider: ModelProvider, seed: int):
    common = {
        "n_estimators": 100,
        "max_depth": 4,
        "learning_rate": 0.05,
        "random_state": seed,
        "n_jobs": 1,
    }
    if provider == "lightgbm":
        from lightgbm import LGBMClassifier, LGBMRegressor

        classifier = LGBMClassifier(
            **common,
            verbosity=-1,
        )
        quantiles = tuple(
            LGBMRegressor(
                **common,
                objective="quantile",
                alpha=alpha,
                verbosity=-1,
            )
            for alpha in (0.1, 0.5, 0.9)
        )
        return classifier, quantiles
    if provider == "xgboost":
        from xgboost import XGBClassifier, XGBRegressor

        classifier = XGBClassifier(
            **common,
            eval_metric="logloss",
        )
        quantiles = tuple(
            XGBRegressor(
                **common,
                objective="reg:quantileerror",
                quantile_alpha=alpha,
            )
            for alpha in (0.1, 0.5, 0.9)
        )
        return classifier, quantiles
    raise ValueError("provider 只允许 lightgbm/xgboost")


def train_prediction_model(
    examples: list[PredictionExample],
    *,
    provider: ModelProvider = "lightgbm",
    seed: int = 0,
) -> TrainedPredictionModel:
    dates = sorted({row.signal_date for row in examples})
    if len(dates) < 40 or len(examples) < 100:
        raise ValueError("训练至少需要 40 个交易日和 100 个样本")
    calibration_count = max(10, len(dates) // 5)
    calibration_dates = set(dates[-calibration_count:])
    training = [
        row for row in examples if row.signal_date not in calibration_dates
    ]
    calibration = [
        row for row in examples if row.signal_date in calibration_dates
    ]
    train_labels = np.asarray([row.next_up for row in training])
    calibration_labels = np.asarray([row.next_up for row in calibration])
    if len(set(train_labels)) < 2 or len(set(calibration_labels)) < 2:
        raise ValueError("训练和校准窗口都必须同时包含上涨与下跌样本")
    classifier, quantile_models = _models(provider, seed)
    classifier.fit(_matrix(training), train_labels)
    raw_calibration = classifier.predict_proba(_matrix(calibration))[:, 1]
    calibrator = IsotonicRegression(
        y_min=0,
        y_max=1,
        out_of_bounds="clip",
    )
    calibrator.fit(raw_calibration, calibration_labels)
    portable_calibrator = IsotonicCalibrator(
        x=[float(value) for value in calibrator.X_thresholds_],
        y=[float(value) for value in calibrator.y_thresholds_],
    )
    targets = np.asarray([row.next_return for row in training])
    for model in quantile_models:
        model.fit(_matrix(training), targets)
    return TrainedPredictionModel(
        provider=provider,
        classifier=classifier,
        calibrator=portable_calibrator,
        quantile_models=quantile_models,
    )
