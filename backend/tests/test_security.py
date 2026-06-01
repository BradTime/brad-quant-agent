"""生产安全默认的回归测试（JWT 密钥强制 / 环境判定 / CORS 局域网生产收紧）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret="change-me-in-production")


def test_production_allows_strong_jwt_secret():
    s = Settings(app_env="production", jwt_secret="a-strong-secret-value")
    assert s.is_production is True


def test_dev_allows_default_jwt_secret():
    s = Settings(app_env="dev", jwt_secret="change-me-in-production")
    assert s.is_production is False


def test_lan_cors_disabled_in_production():
    from app.core import cors

    prod = Settings(app_env="production", jwt_secret="strong", cors_allow_private_lan=True)
    # 生产即使开启 cors_allow_private_lan，局域网来源也不应放行
    monkey_origin = "http://192.168.1.50:3000"
    # 直接用生产配置实例校验判定逻辑
    original = cors.settings
    try:
        cors.settings = prod  # type: ignore[assignment]
        assert cors.is_allowed_origin(monkey_origin) is False
    finally:
        cors.settings = original  # type: ignore[assignment]
