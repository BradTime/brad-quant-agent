"""H19：早报新闻主窗口 / 最大回退年龄 / 缺失标注。"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.extra import NewsItem
from app.services import brief

_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def news_sqlite(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[NewsItem.__table__])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(brief, "SessionLocal", sessions)
    monkeypatch.setattr(brief.settings, "brief_news_window_hours", 48)
    monkeypatch.setattr(brief.settings, "brief_news_max_fallback_age_hours", 168)
    try:
        yield sessions
    finally:
        engine.dispose()


def _add_news(
    sessions,
    *,
    title: str,
    published_at: datetime | None,
    fetched_at: datetime | None = None,
    code: str = "600000.SH",
) -> None:
    with sessions() as session:
        session.add(
            NewsItem(
                id=uuid4().hex,
                code=code,
                title=title,
                published_at=published_at,
                fetched_at=fetched_at or published_at or datetime.now(_TZ),
                source="test",
            )
        )
        session.commit()


def test_recent_window_hit_no_fallback(news_sqlite, monkeypatch):
    now = datetime(2026, 6, 1, 10, 0, 0)

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return now.replace(tzinfo=tz) if tz is not None else now

    monkeypatch.setattr(brief, "datetime", _FakeDateTime)

    _add_news(news_sqlite, title="日内新闻", published_at=now - timedelta(hours=12))
    _add_news(news_sqlite, title="过旧新闻", published_at=now - timedelta(days=30))

    result = brief._recent_news(["600000.SH"])
    assert result["fallbackUsed"] is False
    assert result["recentMissing"] is False
    assert [n["title"] for n in result["items"]] == ["日内新闻"]
    assert result["newestAt"] is not None


def test_fallback_within_max_age(news_sqlite, monkeypatch):
    now = datetime(2026, 6, 1, 10, 0, 0)

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return now.replace(tzinfo=tz) if tz is not None else now

    monkeypatch.setattr(brief, "datetime", _FakeDateTime)

    _add_news(
        news_sqlite,
        title="三天前",
        published_at=now - timedelta(days=3),
    )
    _add_news(
        news_sqlite,
        title="一个月前",
        published_at=now - timedelta(days=30),
    )

    result = brief._recent_news(["600000.SH"])
    assert result["fallbackUsed"] is True
    assert result["recentMissing"] is False
    assert [n["title"] for n in result["items"]] == ["三天前"]


def test_too_old_marks_recent_missing(news_sqlite, monkeypatch):
    now = datetime(2026, 6, 1, 10, 0, 0)

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return now.replace(tzinfo=tz) if tz is not None else now

    monkeypatch.setattr(brief, "datetime", _FakeDateTime)

    _add_news(
        news_sqlite,
        title="古董新闻",
        published_at=now - timedelta(days=40),
        fetched_at=now - timedelta(hours=1),  # 刚入库也不能当近期
    )

    result = brief._recent_news(["600000.SH"])
    assert result["items"] == []
    assert result["fallbackUsed"] is False
    assert result["recentMissing"] is True
    assert result["newestAt"] is None
