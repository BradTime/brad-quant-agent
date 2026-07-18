"""AI chat request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    content: str = Field(min_length=1, max_length=16_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=1)
    sessionId: str | None = Field(default=None, min_length=1, max_length=36)
    # 界面上下文（如当前个股）。服务端会作为不可信元数据包裹，绝不作为 system 指令。
    contextHint: str | None = Field(default=None, max_length=4_000)


class MemoryUpsertRequest(BaseModel):
    """A preference the user explicitly chose to persist."""

    model_config = ConfigDict(extra="forbid")

    key: Literal[
        "answer_style",
        "risk_preference",
        "language",
        "watch_focus",
    ]
    value: str = Field(min_length=1, max_length=64)

    @field_validator("key", "value")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("偏好键和值不能为空")
        return value


class ResearchRequest(BaseModel):
    """自主深度研究请求：单个研究问题 + 可选界面上下文（不可信元数据）。"""

    question: str = Field(min_length=1, max_length=2_000)
    contextHint: str | None = Field(default=None, max_length=4_000)
