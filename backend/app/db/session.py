"""Database engine and session factory (sync SQLAlchemy 2.0)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

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
