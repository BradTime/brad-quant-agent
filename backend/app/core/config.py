"""Application settings loaded from environment (.env)."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Quant Agent Backend"
    version: str = "0.1.0"
    port: int = 3001
    # 运行环境：dev / production —— 用于生产收紧安全默认（CORS、JWT 密钥校验）
    app_env: str = "dev"

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
    # 混合检索：向量召回 + 关键词(ILIKE)召回，用 RRF 融合排序（关闭则纯向量）
    rag_hybrid_enabled: bool = True
    # 混合检索每路候选池大小（融合后再截断到 rag_top_k）
    rag_hybrid_candidates: int = 20
    # HNSW 检索精度参数 ef_search（越大越准越慢；需已建 HNSW 索引才生效）
    rag_hnsw_ef_search: int = 64

    # 盘前早报生成引擎：graph（LangGraph 多智能体）/ single（单轮合成，兜底）
    brief_engine: str = "graph"
    # 多智能体早报 evaluator-optimizer 反思回环的最大修订轮数（0=关闭修订；上限见 brief_graph 封顶）
    brief_max_revisions: int = 1

    # AI 成本闸：每用户每日生成配额（防超额/滥用；<=0 表示不限），按昂贵程度分桶
    ai_daily_quota_chat: int = 100
    ai_daily_quota_research: int = 20
    ai_daily_quota_brief: int = 20
    # 重型生成（research/brief）两次之间的最小间隔秒（防连点；<=0 不限）
    ai_heavy_min_interval_sec: int = 5
    # 回测每用户每日配额（计算密集；<=0 不限）
    ai_daily_quota_backtest: int = 50

    # 可观测（Sentry）：仅当 sentry_dsn 非空时启用；默认关、零开销、不外联
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # 可观测（LangSmith）：仅当 langchain_api_key 非空时启用追踪
    langchain_tracing: bool = True
    langchain_api_key: str = ""
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_project: str = "brad-quant-agent"

    # LLMQuant Data（经官方 MCP server 取美国宏观快照，补早报"海外宏观"缺口）
    # 需 LLMQUANT_API_KEY（llmquantdata.com）+ 运行环境有 npx；缺任一则降级为空
    llmquant_enabled: bool = True
    llmquant_api_key: str = ""
    llmquant_base_url: str = "https://api.llmquantdata.com"
    llmquant_macro_indicators: str = (
        "us.cpi.headline,us.pce.core,us.unemployment_rate,"
        "us.rates.fed_funds,us.yield.10y,us.yield_curve.10y_2y"
    )
    # 进程内 TTL 缓存秒数（默认 12h）：避免每次早报生成都 npx 取数 + 计费
    llmquant_cache_ttl_seconds: int = 43200
    # 量化知识背景（wiki 语义检索）：给「消息面/研究分析师」补概念背景
    llmquant_knowledge_enabled: bool = True
    llmquant_knowledge_topk: int = 4

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"prod", "production"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def index_code_list(self) -> list[str]:
        return [c.strip() for c in self.index_codes.split(",") if c.strip()]

    @property
    def llmquant_macro_list(self) -> list[str]:
        return [c.strip() for c in self.llmquant_macro_indicators.split(",") if c.strip()]

    @model_validator(mode="after")
    def _enforce_production_security(self) -> "Settings":
        # 生产环境严禁使用默认 JWT 密钥（启动即失败，避免可伪造令牌的弱配置上线）
        if self.is_production and self.jwt_secret == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "生产环境（APP_ENV=production）必须设置非默认 JWT_SECRET"
            )
        return self


@lru_cache
def get_settings() -> "Settings":
    return Settings()


settings = get_settings()
