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

    # 行情调度器
    enable_scheduler: bool = True
    quote_refresh_seconds: int = 10
    index_refresh_seconds: int = 30
    ws_push_seconds: int = 3
    index_codes: str = "000001.SH,399001.SZ,399006.SZ"
    # 免费实时源限流/卡顿时的硬超时（秒）：超时即降级为空，避免请求/任务无限挂起。
    realtime_fetch_timeout_seconds: int = 20

    # 盘前早报（Phase 2）：每日定时生成全局早报
    enable_brief_scheduler: bool = True
    brief_cron_hour: int = 8
    brief_cron_minute: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def index_code_list(self) -> list[str]:
        return [c.strip() for c in self.index_codes.split(",") if c.strip()]


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
