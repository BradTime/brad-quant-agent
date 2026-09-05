"""Pydantic shapes for versioned persisted JSON (H17)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyParamsPayload(BaseModel):
    """Strategy ``params_json`` inner payload (numeric params map)."""

    model_config = ConfigDict(extra="allow")

    # keys vary by builtin_type; values must be finite numbers when present
    # validation against catalog happens in strategy.validate_params


class BacktestMetricsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    totalReturn: float | None = None
    totalReturnPercent: float | None = None
    annualReturnPercent: float | None = None
    maxDrawdownPercent: float | None = None
    sharpeRatio: float | None = None
    winRate: float | None = None
    tradeCount: int | None = None


class BacktestConfigPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategyType: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    initialCapital: float | None = None
    slippage: float | None = None
    engine: str | None = None
    frequency: str | None = None


class BriefDataPackSnapshot(BaseModel):
    """Outer snapshot stored in ``morning_briefs.data_pack_json`` (after unwrap)."""

    model_config = ConfigDict(extra="allow")

    engine: str = "single"
    pack: dict[str, Any] = Field(default_factory=dict)
    agentTrace: list[dict[str, Any]] = Field(default_factory=list)
