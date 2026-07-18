"""回测请求 schema（Phase 4 M3）。"""

from __future__ import annotations

import itertools
import math
import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.backtest.base import BacktestEngineName, BacktestFrequency
from app.providers.symbols import infer_exchange

StrategyType = Literal["dual_ma", "rsi", "boll", "momentum"]
GridSortMetric = Literal[
    "totalReturnPercent",
    "annualReturnPercent",
    "sharpeRatio",
    "maxDrawdownPercent",
    "winRate",
    "totalTrades",
    "excessReturnPercent",
]

MAX_BACKTEST_DAYS = 3660
MAX_INITIAL_CAPITAL = 1_000_000_000_000.0
MAX_GRID_COMBOS = 64
_CODE_RE = re.compile(r"^(?P<six>\d{6})(?:\.(?P<exchange>SH|SZ|BJ))?$", re.IGNORECASE)


def normalize_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("codes 必须是数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("股票代码必须是字符串")
        match = _CODE_RE.fullmatch(raw.strip())
        if match is None:
            raise ValueError(f"非法 A 股代码: {raw}")
        six = match.group("six")
        inferred = infer_exchange(six)
        supplied = match.group("exchange")
        if supplied is not None and supplied.upper() != inferred:
            raise ValueError(f"股票代码交易所不匹配: {raw}")
        code = f"{six}.{inferred}"
        if code not in seen:
            normalized.append(code)
            seen.add(code)
    if not 1 <= len(normalized) <= 20:
        raise ValueError("codes 去重后数量必须在 1 到 20 之间")
    return normalized


def _validate_params(strategy_type: str, params: Any) -> dict[str, int | float]:
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")
    from app.services.strategy import validate_params

    _, normalized = validate_params(strategy_type, params)
    return normalized


def _validate_dates(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start 不能晚于 end")
    if (end - start).days > MAX_BACKTEST_DAYS:
        raise ValueError("回测区间最长为 10 年")


class _BacktestRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategyType: StrategyType = "dual_ma"
    codes: list[str]
    start: date
    end: date
    initialCapital: float = Field(
        default=1_000_000.0,
        gt=0,
        le=MAX_INITIAL_CAPITAL,
        allow_inf_nan=False,
    )
    slippage: float = Field(default=0.0, ge=0, le=0.1, allow_inf_nan=False)
    engine: BacktestEngineName = "native"
    frequency: BacktestFrequency = "1d"

    @field_validator("codes", mode="before")
    @classmethod
    def validate_codes(cls, value: Any) -> list[str]:
        return normalize_codes(value)

    @field_validator("initialCapital", "slippage", mode="before")
    @classmethod
    def validate_finite_number(cls, value: Any) -> Any:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float, Decimal))
            or not math.isfinite(float(value))
        ):
            raise ValueError("必须是有限数字")
        return value

    @model_validator(mode="after")
    def validate_date_range(self):
        _validate_dates(self.start, self.end)
        return self


class RunBacktestRequest(_BacktestRequestBase):
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_strategy_params(self):
        self.params = _validate_params(self.strategyType, self.params)
        return self


class GridSearchRequest(_BacktestRequestBase):
    paramGrid: dict[str, list[Any]]
    sortBy: GridSortMetric = "sharpeRatio"

    @field_validator("paramGrid", mode="before")
    @classmethod
    def validate_grid_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("paramGrid 必须是非空对象")
        for key, candidates in value.items():
            if not isinstance(key, str):
                raise ValueError("paramGrid 键必须是字符串")
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 10:
                raise ValueError(f"参数 {key} 的候选值数量必须在 1 到 10 之间")
            for candidate in candidates:
                if (
                    isinstance(candidate, bool)
                    or not isinstance(candidate, (int, float))
                    or not math.isfinite(float(candidate))
                ):
                    raise ValueError(f"参数 {key} 的候选值必须是有限数字")
        return value

    @model_validator(mode="after")
    def validate_grid_combinations(self):
        combo_count = math.prod(len(values) for values in self.paramGrid.values())
        if combo_count > MAX_GRID_COMBOS:
            raise ValueError(f"参数组合不能超过 {MAX_GRID_COMBOS} 组")
        keys = list(self.paramGrid)
        for values in itertools.product(*(self.paramGrid[key] for key in keys)):
            _validate_params(self.strategyType, dict(zip(keys, values, strict=True)))
        return self
