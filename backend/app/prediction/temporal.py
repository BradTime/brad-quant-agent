"""Purged expanding-window folds for cross-sectional daily examples."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.prediction.features import PredictionExample


@dataclass(frozen=True)
class PurgedFold:
    train: tuple[PredictionExample, ...]
    validation: tuple[PredictionExample, ...]
    train_end: date
    validation_start: date
    validation_end: date


def purged_walk_forward(
    examples: list[PredictionExample],
    *,
    minimum_train_dates: int = 252,
    validation_dates: int = 63,
    embargo_dates: int = 1,
    max_folds: int = 5,
) -> list[PurgedFold]:
    if minimum_train_dates < 20:
        raise ValueError("minimum_train_dates 必须至少为 20")
    if validation_dates < 1 or embargo_dates < 1 or max_folds < 1:
        raise ValueError("validation/embargo/max_folds 必须大于 0")
    dates = sorted({row.signal_date for row in examples})
    folds: list[PurgedFold] = []
    test_start = minimum_train_dates + embargo_dates
    while test_start + validation_dates <= len(dates):
        train_end_index = test_start - embargo_dates
        train_dates = set(dates[:train_end_index])
        embargo_start = dates[train_end_index]
        validation_slice = dates[
            test_start : test_start + validation_dates
        ]
        validation_set = set(validation_slice)
        train = tuple(
            row
            for row in examples
            if row.signal_date in train_dates
            and row.label_date < embargo_start
        )
        validation = tuple(
            row for row in examples if row.signal_date in validation_set
        )
        if train and validation:
            folds.append(
                PurgedFold(
                    train=train,
                    validation=validation,
                    train_end=dates[train_end_index - 1],
                    validation_start=validation_slice[0],
                    validation_end=validation_slice[-1],
                )
            )
        test_start += validation_dates
    if len(folds) <= max_folds:
        return folds
    if max_folds == 1:
        return [folds[-1]]
    indices = [
        round(index * (len(folds) - 1) / (max_folds - 1))
        for index in range(max_folds)
    ]
    return [folds[index] for index in indices]
