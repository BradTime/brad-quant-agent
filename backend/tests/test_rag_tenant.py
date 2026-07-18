"""RAG tenant-boundary tests for public news/global brief retrieval."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.brief import MorningBrief
from app.models.document import Document
from app.services import rag


@pytest.fixture
def rag_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    MorningBrief.__table__.create(bind=engine)
    Document.__table__.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(rag, "SessionLocal", test_session)
    try:
        yield test_session
    finally:
        engine.dispose()


def test_brief_backfill_indexes_only_global_briefs_and_purges_private_docs(
    rag_db,
    monkeypatch,
):
    with rag_db() as session:
        session.add_all(
            [
                MorningBrief(
                    id="global-brief",
                    user_id=None,
                    trade_date=date(2026, 7, 17),
                    status="ready",
                    title="全局早报",
                    content="公开内容",
                ),
                MorningBrief(
                    id="private-brief",
                    user_id="user-a",
                    trade_date=date(2026, 7, 17),
                    status="ready",
                    title="用户早报",
                    content="自选股隐私内容",
                ),
                Document(
                    id="private-doc",
                    source="brief",
                    ref_id="private-brief",
                    title="用户早报",
                    chunk="自选股隐私内容",
                    chunk_index=0,
                    embedding=None,
                ),
            ]
        )
        session.commit()

    indexed: list[str] = []

    def fake_index_document(**kwargs):
        indexed.append(kwargs["ref_id"])
        return 1

    monkeypatch.setattr(rag, "index_document", fake_index_document)

    assert rag.backfill_briefs(limit=60) == 1
    assert indexed == ["global-brief"]
    with rag_db() as session:
        assert session.execute(
            select(Document).where(Document.id == "private-doc")
        ).scalar_one_or_none() is None


def test_public_retrieval_scope_excludes_private_brief_ids():
    statement = rag._apply_public_scope(select(Document))
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "morning_briefs.user_id IS NULL" in sql
    assert "documents.source !=" in sql


def test_keyword_retrieval_returns_news_and_ready_global_briefs_only(rag_db):
    with rag_db() as session:
        session.add_all(
            [
                MorningBrief(
                    id="global-ready",
                    user_id=None,
                    trade_date=date(2026, 7, 17),
                    status="ready",
                    title="全局",
                    content="测试",
                ),
                MorningBrief(
                    id="global-failed",
                    user_id=None,
                    trade_date=date(2026, 7, 17),
                    status="failed",
                    title="失败",
                    content="测试",
                ),
                MorningBrief(
                    id="private-ready",
                    user_id="user-a",
                    trade_date=date(2026, 7, 17),
                    status="ready",
                    title="私有",
                    content="测试",
                ),
                Document(
                    id="doc-global",
                    source="brief",
                    ref_id="global-ready",
                    title="全局测试",
                    chunk="测试内容",
                    chunk_index=0,
                ),
                Document(
                    id="doc-failed",
                    source="brief",
                    ref_id="global-failed",
                    title="失败测试",
                    chunk="测试内容",
                    chunk_index=0,
                ),
                Document(
                    id="doc-private",
                    source="brief",
                    ref_id="private-ready",
                    title="私有测试",
                    chunk="测试内容",
                    chunk_index=0,
                ),
                Document(
                    id="doc-news",
                    source="news",
                    ref_id="news-1",
                    title="新闻测试",
                    chunk="测试内容",
                    chunk_index=0,
                ),
            ]
        )
        session.commit()

        all_rows = rag._keyword_rows(session, ["测试"], 10, None)
        brief_rows = rag._keyword_rows(session, ["测试"], 10, "brief")
        news_rows = rag._keyword_rows(session, ["测试"], 10, "news")

    assert {row.id for row in all_rows} == {"doc-global", "doc-news"}
    assert [row.id for row in brief_rows] == ["doc-global"]
    assert [row.id for row in news_rows] == ["doc-news"]


def test_vector_retrieval_statement_always_contains_public_scope():
    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return FakeResult()

    session = FakeSession()
    rag._vector_rows(session, [0.0] * 512, 5, None)
    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))

    assert "morning_briefs.user_id IS NULL" in sql
    assert "morning_briefs.status = 'ready'" in sql
