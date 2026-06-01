"""Create tables from the ORM metadata.

Phase 0 uses ``create_all`` for speed; switch to Alembic migrations once the
schema stabilizes.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine

logger = logging.getLogger(__name__)


def init_db() -> None:
    import app.models  # noqa: F401  (register mappers on Base.metadata)

    # RAG 向量检索依赖 pgvector 扩展；建表前确保扩展存在（需镜像 pgvector/pgvector）。
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("创建 pgvector 扩展失败（RAG 检索将不可用）：%s", exc)

    Base.metadata.create_all(bind=engine)
