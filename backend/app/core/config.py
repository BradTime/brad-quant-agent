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
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # 开发环境允许局域网 IP 访问前端（如 http://192.168.x.x:3000）
    cors_allow_private_lan: bool = True

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

    # RAG（检索增强）：可插拔 embedding 后端
    # embedding_provider: local（本地 sentence-transformers）/ api（OpenAI 兼容）
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dim: int = 512
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    rag_top_k: int = 5
    # RAG 总开关：关闭后早报/问答不做检索增强（不影响主流程）
    rag_enabled: bool = True
    # 启动时后台预热本地 embedding 模型（守护线程，不阻塞启动）
    embedding_warm_on_start: bool = True

    # 盘前早报生成引擎：graph（LangGraph 多智能体）/ single（单轮合成，兜底）
    brief_engine: str = "graph"

    # 可观测（LangSmith）：仅当 langchain_api_key 非空时启用追踪
    langchain_tracing: bool = True
    langchain_api_key: str = ""
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_project: str = "brad-quant-agent"

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
