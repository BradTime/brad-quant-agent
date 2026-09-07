"""Database engine and session factory (sync SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "future": True,
    "pool_size": max(1, int(settings.db_pool_size)),
    "max_overflow": max(0, int(settings.db_max_overflow)),
    "pool_recycle": max(60, int(settings.db_pool_recycle_seconds)),
    "pool_timeout": max(1, int(settings.db_pool_timeout_seconds)),
}
# SQLite 不支持 QueuePool 的 pool_size 语义；用 StaticPool/NullPool 时忽略这些参数
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
