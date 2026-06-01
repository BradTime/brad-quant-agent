"""RAG 文档块（Phase A）：把新闻 / 历史早报等语料切块 + 向量化后落库，供检索增强。

向量列用 pgvector 的 ``Vector``，维度取 ``settings.embedding_dim``（默认 512，bge-small-zh）。
切换 embedding 模型若维度不同，需重建该表（或新增列）。
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha1(source|ref_id|chunk_index)
    source: Mapped[str] = mapped_column(String(32), index=True, default="")  # news / brief / financial
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    chunk: Mapped[str] = mapped_column(Text, default="")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )
    meta: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
