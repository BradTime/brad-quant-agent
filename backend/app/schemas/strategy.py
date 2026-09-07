"""Request schemas for persisted built-in strategies."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrategyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("name", check_fields=False)
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("策略名称不能为空")
        return value


class StrategyCreateRequest(_StrategyBody):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)
    builtin_type: str = Field(alias="builtinType")
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyUpdateRequest(_StrategyBody):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    builtin_type: str | None = Field(default=None, alias="builtinType")
    params: dict[str, Any] | None = None
