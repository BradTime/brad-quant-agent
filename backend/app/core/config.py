"""Application settings loaded from environment (.env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Quant Agent Backend"
    version: str = "0.1.0"
    port: int = 3001

    # CORS：逗号分隔的来源列表
    cors_origins: str = "http://localhost:3000"

    # Database
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/quant_agent"

    # DeepSeek（OpenAI 兼容）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # JWT
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
