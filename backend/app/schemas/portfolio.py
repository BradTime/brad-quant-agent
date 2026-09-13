"""Strict request contracts for M3 regime and allocation previews."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class RegimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indexCloses: list[float] = Field(min_length=60, max_length=1500)
    marketBreadth: float = Field(ge=0, le=1, allow_inf_nan=False)
    asOf: date


class AuthoritativeAllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(min_length=1, max_length=20)
    asOf: date
