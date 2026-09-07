"""DeepSeek client (OpenAI-compatible). Imported lazily so the package is only
required when the AI feature is actually used."""

from __future__ import annotations

from typing import Any

from app.core.config import settings


def completion_options() -> dict[str, Any]:
    """Force non-thinking mode for the platform's existing tool-call protocol."""
    if settings.deepseek_model.lower().startswith("deepseek-v4-"):
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def get_client():
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 设置后重试")
    from openai import OpenAI

    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
