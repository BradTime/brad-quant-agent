"""生产安全默认的回归测试（JWT 密钥强制 / 环境判定 / CORS 局域网生产收紧）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_PROD_OUTBOX_KEY = "ZJN11AF-N3EN-1YNbmjiPQPLUSORpzWElFTdmo_f9sU="


def test_production_rejects_default_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret="change-me-in-production")


def test_production_allows_strong_jwt_secret():
    s = Settings(
        app_env="production",
        jwt_secret="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        smtp_host="smtp.example.com",
        smtp_user="mailer",
        smtp_password="secret",
        smtp_from="noreply@example.com",
        frontend_url="https://example.com",
        auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
    )
    assert s.is_production is True


def test_dev_allows_default_jwt_secret():
    s = Settings(app_env="dev", jwt_secret="change-me-in-production")
    assert s.is_production is False


def test_lan_cors_disabled_in_production():
    from app.core import cors

    prod = Settings(
        app_env="production",
        jwt_secret="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        smtp_host="smtp.example.com",
        smtp_user="mailer",
        smtp_password="secret",
        smtp_from="noreply@example.com",
        frontend_url="https://example.com",
        auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
        cors_allow_private_lan=True,
    )
    # 生产即使开启 cors_allow_private_lan，局域网来源也不应放行
    monkey_origin = "http://192.168.1.50:3000"
    # 直接用生产配置实例校验判定逻辑
    original = cors.settings
    try:
        cors.settings = prod  # type: ignore[assignment]
        assert cors.is_allowed_origin(monkey_origin) is False
    finally:
        cors.settings = original  # type: ignore[assignment]
