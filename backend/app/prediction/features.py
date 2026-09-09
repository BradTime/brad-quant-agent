"""PIT-safe daily features and next-open-to-close labels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from app.backtest.data import Bar
from app.backtest.universe import expected_session_dates

FEATURE_SCHEMA_VERSION = "daily-pit-v1"
MIN_HISTORY = 21


@dataclass(frozen=True)
class PredictionFeature:
    code: str
    signal_date: date
    features: dict[str, float]


@dataclass(frozen=True)
class PredictionExample(PredictionFeature):
    label_date: date
    next_return: float
    next_up: int


def _returns(values: list[float]) -> list[float]:
    return [
        values[index] / values[index - 1] - 1
        for index in range(1, len(values))
        if values[index - 1] > 0
    ]


def _zscore_last(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    return (values[-1] - mean) / std if std > 0 else 0.0


def _features_at(bars: list[Bar], index: int) -> dict[str, float] | None:
    signal = bars[index]
    window = bars[index - 20 : index + 1]
    closes = [bar.close for bar in window]
    if len(closes) != 21 or any(
        value <= 0 or not math.isfinite(value) for value in closes
    ):
        return None
    amounts = [
        float(bar.amount)
        for bar in window[-20:]
        if bar.amount is not None
        and float(bar.amount) > 0
        and math.isfinite(float(bar.amount))
    ]
    volumes = [
        float(bar.volume)
        for bar in window[-20:]
        if bar.volume is not None and bar.volume > 0
    ]
    if len(amounts) != 20 or len(volumes) != 20:
        return None
    returns = _returns(closes)
    if len(returns) != 20:
        return None
    mean_return = sum(returns) / len(returns)
    volatility = math.sqrt(
        sum((value - mean_return) ** 2 for value in returns)
        / len(returns)
    )
    return {
        "return1": closes[-1] / closes[-2] - 1,
        "return5": closes[-1] / closes[-6] - 1,
        "return20": closes[-1] / closes[0] - 1,
        "volatility20": volatility,
        "range1": (
            (signal.high - signal.low) / signal.close
            if signal.close > 0
            else 0.0
        ),
        "amountZ20": _zscore_last(amounts),
        "volumeZ20": _zscore_last(volumes),
    }


def build_daily_examples(
    bars_by_code: dict[str, list[Bar]],
    *,
    eligible_by_date: dict[str, tuple[str, ...]] | None = None,
) -> list[PredictionExample]:
    examples: list[PredictionExample] = []
    eligible_sets = (
        {
            day: set(codes)
            for day, codes in eligible_by_date.items()
        }
        if eligible_by_date is not None
        else None
    )
    for code, raw_bars in bars_by_code.items():
        bars = sorted(raw_bars, key=lambda bar: bar.date)
        for index in range(MIN_HISTORY - 1, len(bars) - 1):
            signal = bars[index]
            next_bar = bars[index + 1]
            signal_day = (
                signal.date.date()
                if hasattr(signal.date, "date")
                else signal.date
            )
            next_day = (
                next_bar.date.date()
                if hasattr(next_bar.date, "date")
                else next_bar.date
            )
            expected = expected_session_dates(signal_day, next_day)
            if len(expected) != 2 or expected[-1] != next_day.isoformat():
                continue
            if eligible_sets is not None and code not in eligible_sets.get(
                signal_day.isoformat(), ()
            ):
                continue
            features = _features_at(bars, index)
            if features is None or next_bar.open <= 0:
                continue
            next_return = next_bar.close / next_bar.open - 1
            if not math.isfinite(next_return):
                continue
            examples.append(
                PredictionExample(
                    code=code,
                    signal_date=signal_day,
                    label_date=next_day,
                    features=features,
                    next_return=next_return,
                    next_up=int(next_return > 0),
                )
            )
    return sorted(examples, key=lambda row: (row.signal_date, row.code))


def build_latest_features(
    bars_by_code: dict[str, list[Bar]],
    *,
    signal_date: date,
    eligible_codes: set[str],
) -> list[PredictionFeature]:
    features: list[PredictionFeature] = []
    for code in sorted(eligible_codes):
        bars = sorted(bars_by_code.get(code, []), key=lambda bar: bar.date)
        indexes = [
            index
            for index, bar in enumerate(bars)
            if (
                bar.date.date()
                if hasattr(bar.date, "date")
                else bar.date
            )
            <= signal_date
        ]
        if not indexes:
            continue
        values = _features_at(bars, indexes[-1])
        bar_day = (
            bars[indexes[-1]].date.date()
            if hasattr(bars[indexes[-1]].date, "date")
            else bars[indexes[-1]].date
        )
        if values is None or bar_day != signal_date:
            continue
        features.append(
            PredictionFeature(
                code=code,
                signal_date=signal_date,
                features=values,
            )
        )
    return features
