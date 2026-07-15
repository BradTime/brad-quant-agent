"""回测请求 schema（Phase 4 M3）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.backtest.base import BacktestEngineName, BacktestFrequency


class RunBacktestRequest(BaseModel):
    strategyType: str = "dual_ma"
    params: dict = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list)
    start: str
    end: str
    initialCapital: float = 1_000_000.0
    slippage: float = 0.0
    engine: BacktestEngineName = "native"
    frequency: BacktestFrequency = "1d"


class GridSearchRequest(BaseModel):
    strategyType: str = "dual_ma"
    paramGrid: dict[str, list[float]] = Field(default_factory=dict)  # {参数: [候选值...]}
    codes: list[str] = Field(default_factory=list)
    start: str
    end: str
    initialCapital: float = 1_000_000.0
    slippage: float = 0.0
    engine: BacktestEngineName = "native"
    sortBy: str = "sharpeRatio"
    frequency: BacktestFrequency = "1d"
