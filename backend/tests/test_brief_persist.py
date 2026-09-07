"""H13：早报/研究落库协议——generating 先行；失败不伪造成功。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import deep_research
from app.db.base import Base
from app.models.brief import MorningBrief
from app.models.research import ResearchReport
from app.services import brief


@pytest.fixture
def brief_sqlite(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[MorningBrief.__table__, ResearchReport.__table__],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(brief, "SessionLocal", sessions)
    monkeypatch.setattr(deep_research, "SessionLocal", sessions)
    monkeypatch.setattr(brief, "market_today", lambda: date(2024, 6, 1))
    try:
        yield sessions
    finally:
        engine.dispose()


def test_ready_persist_failure_leaves_generating(brief_sqlite, monkeypatch):
    """ready 落库失败时不得伪装成功；库内保持 generating。"""
    real = brief._persist
    ready_attempts = {"n": 0}

    def flaky(*args, **kwargs):
        status = args[5] if len(args) > 5 else kwargs.get("status")
        if status == "ready":
            ready_attempts["n"] += 1
            if ready_attempts["n"] == 1:
                raise RuntimeError("db down")
        return real(*args, **kwargs)

    monkeypatch.setattr(brief, "_persist", flaky)
    monkeypatch.setattr(brief, "build_data_pack", lambda _uid: {"ok": True})
    monkeypatch.setattr(brief, "render_data_pack_text", lambda _p: "pack")
    monkeypatch.setattr(
        brief,
        "run_completion_stream",
        lambda *_a, **_k: iter(["hello"]),
    )
    monkeypatch.setattr(brief.settings, "brief_engine", "single")

    events = list(brief.stream_generate("user-1"))
    assert any(
        isinstance(e, dict) and e.get("error") == "persist_failed" for e in events
    )
    with brief.SessionLocal() as session:
        rows = list(session.execute(select(MorningBrief)).scalars())
        assert len(rows) == 1
        assert rows[0].status == "generating"
        assert rows[0].content == ""


def test_generate_returns_this_run_not_old_ready(brief_sqlite, monkeypatch):
    """generate() 必须返回本次 ID，即使库里已有旧 ready。"""
    old_id = uuid4().hex
    with brief.SessionLocal() as session:
        session.add(
            MorningBrief(
                id=old_id,
                user_id="u1",
                trade_date=date(2024, 5, 31),
                status="ready",
                title="old",
                content="旧早报",
            )
        )
        session.commit()

    monkeypatch.setattr(brief, "build_data_pack", lambda _uid: {})
    monkeypatch.setattr(brief, "render_data_pack_text", lambda _p: "x")
    monkeypatch.setattr(
        brief,
        "run_completion_stream",
        lambda *_a, **_k: iter(["新内容"]),
    )
    monkeypatch.setattr(brief.settings, "brief_engine", "single")

    result = brief.generate("u1")
    assert result["id"] != old_id
    assert result["status"] == "ready"
    assert "新内容" in (result.get("content") or "")


def test_research_ready_persist_failure_leaves_generating(brief_sqlite, monkeypatch):
    real = deep_research._persist
    ready_attempts = {"n": 0}

    def flaky(*args, **kwargs):
        status = args[6] if len(args) > 6 else kwargs.get("status")
        if status == "ready":
            ready_attempts["n"] += 1
            if ready_attempts["n"] == 1:
                raise RuntimeError("db down")
        return real(*args, **kwargs)

    monkeypatch.setattr(deep_research, "_persist", flaky)
    monkeypatch.setattr(deep_research, "_plan", lambda *_a, **_k: ["q1"])
    monkeypatch.setattr(
        deep_research,
        "run_chat_collect",
        lambda *_a, **_k: {"answer": "a", "toolsCalled": []},
    )
    monkeypatch.setattr(
        deep_research,
        "run_completion_stream",
        lambda *_a, **_k: iter(["报告正文"]),
    )

    events = list(deep_research.stream_deep_research("测试问题", user_id="u1"))
    assert any(
        isinstance(e, dict) and e.get("error") == "persist_failed" for e in events
    )
    with deep_research.SessionLocal() as session:
        row = session.execute(select(ResearchReport)).scalar_one()
        assert row.status == "generating"
