"""多智能体使用的 Chat 模型（DeepSeek，OpenAI 兼容，经 langchain-openai）。

可观测：仅当配置了 ``langchain_api_key`` 时启用 LangSmith 追踪（设置环境变量），
否则完全离线、不依赖任何外部追踪服务（图内置的逐节点轨迹始终可用）。
"""

from __future__ import annotations

import os

from app.core.config import settings

_langsmith_ready = False


def maybe_enable_langsmith() -> bool:
    """有 key 才开启 LangSmith 追踪；返回是否启用。幂等。"""
    global _langsmith_ready
    if _langsmith_ready:
        return True
    if not (settings.langchain_tracing and settings.langchain_api_key):
        return False
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langchain_endpoint)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
    _langsmith_ready = True
    return True


def get_chat_model(temperature: float = 0.3):
    from langchain_openai import ChatOpenAI

    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 设置后重试")
    maybe_enable_langsmith()
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature,
        timeout=90,
        max_retries=2,
    )
