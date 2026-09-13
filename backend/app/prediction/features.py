"""PIT-safe daily features and next-open-to-close labels."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.backtest.data import Bar
from app.backtest.universe import expected_session_dates

FEATURE_SCHEMA_VERSION = "daily-pit-v2"
MIN_HISTORY = 21
FEATURE_ORDER_V1 = (
    "return1",
    "return5",
    "return20",
    "volatility20",
    "range1",
    "amountZ20",
    "volumeZ20",
)
RANK_FIELDS = (
    "return1",
    "return5",
    "return20",
    "intraday1",
    "volatility20",
    "amountZ20",
)
FEATURE_ORDER_V2 = (
    "return1",
    "return2",
    "return3",
    "return5",
    "return10",
    "return20",
    "volatility20",
    "volatility5",
    "volatilityRatio5To20",
    "range1",
    "intraday1",
    "gap1",
    "closeLocation1",
    "upperShadow1",
    "lowerShadow1",
    "ma5Ratio",
    "ma10Ratio",
    "ma20Ratio",
    "rsi14",
    "amountZ20",
    "volumeZ20",
    "amountRatio5To20",
    "volumeRatio5To20",
    *(f"crossRank_{field}" for field in RANK_FIELDS),
    "marketReturn1",
    "marketReturn5",
    "marketReturn20",
    "marketVolatility20",
    "marketBreadth",
    "marketBreadthImbalance",
    "regimeBull",
    "regimeBear",
    "regimeRange",
    "regimeRiskOff",
)
FEATURE_ORDERS = {
    "daily-pit-v1": FEATURE_ORDER_V1,
    "daily-pit-v2": FEATURE_ORDER_V2,
}
FEATURE_ORDER = FEATURE_ORDERS[FEATURE_SCHEMA_VERSION]


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


def _volatility(values: list[float]) -> float:
    if not values:
        return 0.0
    average = sum(values) / len(values)
    return math.sqrt(
        sum((value - average) ** 2 for value in values)
        / len(values)
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bar_day(bar: Bar) -> date:
    return (
        bar.date.date()
        if hasattr(bar.date, "date")
        else bar.date
    )


def _consecutive_window(window: list[Bar]) -> bool:
    actual = [_bar_day(bar) for bar in window]
    if not actual:
        return False
    return expected_session_dates(
        actual[0], actual[-1]
    ) == tuple(day.isoformat() for day in actual)


def _features_at(bars: list[Bar], index: int) -> dict[str, float] | None:
    signal = bars[index]
    window = bars[index - 20 : index + 1]
    closes = [bar.close for bar in window]
    if (
        len(closes) != 21
        or not _consecutive_window(window)
        or any(
        value <= 0 or not math.isfinite(value) for value in closes
        )
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
    volatility = _volatility(returns)
    returns5 = returns[-5:]
    gains = [max(value, 0.0) for value in returns[-14:]]
    losses = [max(-value, 0.0) for value in returns[-14:]]
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    rsi14 = (
        average_gain / (average_gain + average_loss)
        if average_gain + average_loss > 0
        else 0.5
    )
    spread = signal.high - signal.low
    previous_close = closes[-2]
    return {
        "return1": closes[-1] / closes[-2] - 1,
        "return2": closes[-1] / closes[-3] - 1,
        "return3": closes[-1] / closes[-4] - 1,
        "return5": closes[-1] / closes[-6] - 1,
        "return10": closes[-1] / closes[-11] - 1,
        "return20": closes[-1] / closes[0] - 1,
        "volatility20": volatility,
        "volatility5": _volatility(returns5),
        "volatilityRatio5To20": (
            _volatility(returns5) / volatility
            if volatility > 0
            else 1.0
        ),
        "range1": (
            (signal.high - signal.low) / signal.close
            if signal.close > 0
            else 0.0
        ),
        "intraday1": (
            signal.close / signal.open - 1
            if signal.open > 0
            else 0.0
        ),
        "gap1": (
            signal.open / previous_close - 1
            if previous_close > 0
            else 0.0
        ),
        "closeLocation1": (
            (signal.close - signal.low) / spread - 0.5
            if spread > 0
            else 0.0
        ),
        "upperShadow1": (
            (signal.high - max(signal.open, signal.close))
            / signal.close
            if signal.close > 0
            else 0.0
        ),
        "lowerShadow1": (
            (min(signal.open, signal.close) - signal.low)
            / signal.close
            if signal.close > 0
            else 0.0
        ),
        "ma5Ratio": closes[-1] / _mean(closes[-5:]) - 1,
        "ma10Ratio": closes[-1] / _mean(closes[-10:]) - 1,
        "ma20Ratio": closes[-1] / _mean(closes[-20:]) - 1,
        "rsi14": rsi14 - 0.5,
        "amountZ20": _zscore_last(amounts),
        "volumeZ20": _zscore_last(volumes),
        "amountRatio5To20": _mean(amounts[-5:]) / _mean(amounts) - 1,
        "volumeRatio5To20": _mean(volumes[-5:]) / _mean(volumes) - 1,
    }


def _rank_enrich(
    rows: list[PredictionFeature],
) -> list[PredictionFeature]:
    by_date: dict[date, list[PredictionFeature]] = defaultdict(list)
    for row in rows:
        by_date[row.signal_date].append(row)
    enriched = []
    for day_rows in by_date.values():
        ranks_by_field: dict[str, dict[str, float]] = {}
        for field in RANK_FIELDS:
            ordered = sorted(
                (
                    (row.features[field], row.code)
                    for row in day_rows
                ),
                key=lambda item: (item[0], item[1]),
            )
            denominator = max(len(ordered) - 1, 1)
            field_ranks = {}
            start = 0
            while start < len(ordered):
                end = start + 1
                while (
                    end < len(ordered)
                    and ordered[end][0] == ordered[start][0]
                ):
                    end += 1
                average_rank = (
                    (start + end - 1) / 2 / denominator - 0.5
                )
                for _, code in ordered[start:end]:
                    field_ranks[code] = average_rank
                start = end
            ranks_by_field[field] = field_ranks
        for row in day_rows:
            values = dict(row.features)
            values.update(
                {
                    f"crossRank_{field}": ranks_by_field[field][
                        row.code
                    ]
                    for field in RANK_FIELDS
                }
            )
            if isinstance(row, PredictionExample):
                enriched.append(
                    PredictionExample(
                        code=row.code,
                        signal_date=row.signal_date,
                        features=values,
                        label_date=row.label_date,
                        next_return=row.next_return,
                        next_up=row.next_up,
                    )
                )
            else:
                enriched.append(
                    PredictionFeature(
                        code=row.code,
                        signal_date=row.signal_date,
                        features=values,
                    )
                )
    return sorted(enriched, key=lambda row: (row.signal_date, row.code))


def build_daily_examples(
    bars_by_code: dict[str, list[Bar]],
    *,
    eligible_by_date: dict[str, tuple[str, ...]] | None = None,
    market_features_by_date: dict[date, dict[str, float]]
    | None = None,
) -> list[PredictionExample]:
    signal_rows: list[PredictionFeature] = []
    labels: dict[tuple[date, str], tuple[date, float, int]] = {}
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
        for index in range(MIN_HISTORY - 1, len(bars)):
            signal = bars[index]
            signal_day = _bar_day(signal)
            if eligible_sets is not None and code not in eligible_sets.get(
                signal_day.isoformat(), ()
            ):
                continue
            features = _features_at(bars, index)
            if market_features_by_date is not None:
                market_features = market_features_by_date.get(
                    signal_day
                )
                if market_features is None:
                    continue
                if features is not None:
                    features = {**features, **market_features}
            if features is None:
                continue
            signal_rows.append(
                PredictionFeature(
                    code=code,
                    signal_date=signal_day,
                    features=features,
                )
            )
            if index + 1 >= len(bars):
                continue
            next_bar = bars[index + 1]
            next_day = _bar_day(next_bar)
            expected = expected_session_dates(signal_day, next_day)
            if (
                len(expected) != 2
                or expected[-1] != next_day.isoformat()
                or next_bar.open <= 0
            ):
                continue
            next_return = next_bar.close / next_bar.open - 1
            if math.isfinite(next_return):
                labels[(signal_day, code)] = (
                    next_day,
                    next_return,
                    int(next_return > 0),
                )
    examples = []
    for row in _rank_enrich(signal_rows):
        label = labels.get((row.signal_date, row.code))
        if label is None:
            continue
        examples.append(
            PredictionExample(
                code=row.code,
                signal_date=row.signal_date,
                features=row.features,
                label_date=label[0],
                next_return=label[1],
                next_up=label[2],
            )
        )
    return examples


def build_latest_features(
    bars_by_code: dict[str, list[Bar]],
    *,
    signal_date: date,
    eligible_codes: set[str],
    market_features: dict[str, float] | None = None,
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
        if market_features is not None:
            values = {**values, **market_features}
        features.append(
            PredictionFeature(
                code=code,
                signal_date=signal_date,
                features=values,
            )
        )
    return _rank_enrich(features)
