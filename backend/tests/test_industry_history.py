from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.market import InstrumentIndustryVintage
from app.services import industry_history


def test_industry_history_is_first_observed_append_only(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    InstrumentIndustryVintage.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(industry_history, "SessionLocal", sessions)
    observed = datetime(2026, 9, 8, 8, tzinfo=UTC)
    state = {"industry": "银行", "now": observed}
    monkeypatch.setattr(
        industry_history.market,
        "get_stock_profile",
        lambda code: {
            "code": "600000.SH",
            "industry": state["industry"],
            "source": "test",
        },
    )
    monkeypatch.setattr(
        industry_history.market,
        "canonical_stock_code",
        lambda code: "600000.SH",
    )
    monkeypatch.setattr(industry_history, "_now", lambda: state["now"])

    industry_history.refresh("600000")
    state["now"] = observed + timedelta(hours=1)
    industry_history.refresh("600000")
    state["industry"] = "金融"
    state["now"] = observed + timedelta(days=1)
    industry_history.refresh("600000")
    state["industry"] = "银行"
    state["now"] = observed + timedelta(days=2)
    industry_history.refresh("600000")

    with sessions() as session:
        rows = session.execute(
            select(InstrumentIndustryVintage).order_by(
                InstrumentIndustryVintage.available_at
            )
        ).scalars().all()
    assert len(rows) == 3
    assert rows[0].first_seen_at.replace(tzinfo=UTC) == observed
    assert rows[0].last_seen_at.replace(tzinfo=UTC) == observed
    assert industry_history.industries_asof(
        ["600000.SH"], date(2026, 9, 8)
    ) == {"600000.SH": "银行"}
    assert industry_history.industries_asof(
        ["600000.SH"], date(2026, 9, 9)
    ) == {"600000.SH": "金融"}
    assert industry_history.industries_asof(
        ["600000.SH"], date(2026, 9, 10)
    ) == {"600000.SH": "银行"}
    engine.dispose()
