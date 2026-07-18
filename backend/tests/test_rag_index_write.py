"""H20：RAG 写入校验向量数/维度，失败不删旧索引。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.document import Document
from app.services import rag

_DIM = int(settings.embedding_dim)


def _vec() -> list[float]:
    return [0.01] * _DIM


@pytest.fixture
def rag_sqlite(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Document.__table__])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(rag, "SessionLocal", sessions)
    try:
        yield sessions
    finally:
        engine.dispose()


def test_index_document_rejects_vector_count_mismatch(rag_sqlite, monkeypatch):
    monkeypatch.setattr(
        rag.embeddings,
        "embed_texts",
        lambda texts, is_query=False: [_vec()],  # 1 vec for 2 chunks
    )
    monkeypatch.setattr(rag, "_chunk", lambda text, size=380, overlap=60: ["a", "b"])
    with pytest.raises(ValueError, match="embedding count mismatch"):
        rag.index_document("news", "r1", "t", "body")
    with rag.SessionLocal() as session:
        assert session.execute(select(Document)).scalars().all() == []


def test_index_document_rejects_dim_mismatch_keeps_old(rag_sqlite, monkeypatch):
    monkeypatch.setattr(
        rag.embeddings,
        "embed_texts",
        lambda texts, is_query=False: [_vec() for _ in texts],
    )
    monkeypatch.setattr(rag, "_chunk", lambda text, size=380, overlap=60: ["only"])
    assert rag.index_document("news", "r1", "t", "body") == 1

    monkeypatch.setattr(
        rag.embeddings,
        "embed_texts",
        lambda texts, is_query=False: [[0.1, 0.2] for _ in texts],
    )
    with pytest.raises(ValueError, match="embedding dim mismatch"):
        rag.index_document("news", "r1", "t", "body2")

    with rag.SessionLocal() as session:
        rows = list(session.execute(select(Document)).scalars())
        assert len(rows) == 1
        assert rows[0].chunk == "only"


def test_index_document_returns_actual_insert_count(rag_sqlite, monkeypatch):
    monkeypatch.setattr(
        rag.embeddings,
        "embed_texts",
        lambda texts, is_query=False: [_vec() for _ in texts],
    )
    monkeypatch.setattr(rag, "_chunk", lambda text, size=380, overlap=60: ["a", "b", "c"])
    assert rag.index_document("news", "r2", "t", "body") == 3
