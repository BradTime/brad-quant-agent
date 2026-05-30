"""AI chat request schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=16_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)
    # 服务端注入的上下文（如当前个股），不接受客户端伪造 system 角色
    contextHint: str | None = Field(default=None, max_length=4_000)
