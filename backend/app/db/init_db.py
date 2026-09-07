"""Development-only compatibility helper for creating current ORM tables.

Persistent databases and deployments must use ``alembic upgrade head`` so the
schema revision is recorded and future migrations remain ordered.
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

    # RAG 向量检索加 HNSW 近邻索引（pgvector >= 0.5）：大数据量下远快于精确扫描。
    # 余弦距离 → vector_cosine_ops，与 rag.retrieve 的 cosine_distance 对齐。
    # 失败降级（不支持 HNSW 时检索自动回退精确扫描），不阻断建表。
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_documents_embedding_hnsw "
                    "ON documents USING hnsw (embedding vector_cosine_ops)"
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("创建 documents HNSW 索引失败（检索回退精确扫描）：%s", exc)
