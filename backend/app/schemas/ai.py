"""AI chat request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user"]
    content: str = Field(min_length=1, max_length=16_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    # 界面上下文（如当前个股）。服务端会作为不可信元数据包裹，绝不作为 system 指令。
    contextHint: str | None = Field(default=None, max_length=4_000)
