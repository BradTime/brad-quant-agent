"""Request schemas for built-in and restricted custom strategies."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.strategy_sandbox import MAX_SOURCE_BYTES


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
    definition_type: Literal["builtin", "custom_python"] = Field(
        default="builtin", alias="definitionType"
    )
    builtin_type: str | None = Field(default=None, alias="builtinType")
    source_code: str | None = Field(
        default=None, alias="sourceCode", max_length=MAX_SOURCE_BYTES
    )
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_definition(self):
        if self.definition_type == "builtin":
            if not self.builtin_type or self.source_code is not None:
                raise ValueError("内置策略必须提供 builtinType 且不能提供 sourceCode")
        elif not self.source_code or self.builtin_type is not None:
            raise ValueError("自定义策略必须提供 sourceCode 且不能提供 builtinType")
        return self


class StrategyUpdateRequest(_StrategyBody):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    builtin_type: str | None = Field(default=None, alias="builtinType")
    definition_type: Literal["builtin", "custom_python"] | None = Field(
        default=None, alias="definitionType"
    )
    source_code: str | None = Field(
        default=None, alias="sourceCode", max_length=MAX_SOURCE_BYTES
    )
    params: dict[str, Any] | None = None
    expected_version: int | None = Field(
        default=None, alias="expectedVersion", ge=1
    )


class StrategySignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(default_factory=dict)
    bars: dict[str, list[dict[str, Any]]]

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            size = len(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("context 必须是有限 JSON 数据") from exc
        if size > 65_536:
            raise ValueError("context 不得超过 64 KiB")
        return value

    @field_validator("bars")
    @classmethod
    def validate_bars(
        cls, value: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        if not 1 <= len(value) <= 20:
            raise ValueError("bars 标的数量必须在 1 到 20 之间")
        if any(not rows or len(rows) > 500 for rows in value.values()):
            raise ValueError("每个标的 bars 数量必须在 1 到 500 之间")
        try:
            size = len(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("bars 必须是有限 JSON 数据") from exc
        if size > 1_048_576:
            raise ValueError("bars 不得超过 1 MiB")
        return value
