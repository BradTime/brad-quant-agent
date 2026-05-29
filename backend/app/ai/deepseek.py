"""DeepSeek client (OpenAI-compatible). Imported lazily so the package is only
required when the AI feature is actually used."""

from __future__ import annotations

from app.core.config import settings


def get_client():
    if not settings.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 设置后重试")
    from openai import OpenAI

    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
