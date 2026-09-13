from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest import data as backtest_data
from app.models.extra import CapitalFlowVintage
from app.providers.base import CapitalFlowDTO
from app.services import ingest, market


def test_capital_flow_ingest_is_append_only_and_asof_query_is_stable(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CapitalFlowVintage.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", sessions)
    monkeypatch.setattr(market, "SessionLocal", sessions)
    monkeypatch.setattr(backtest_data, "SessionLocal", sessions)
    observed = datetime(2026, 9, 1, 8, tzinfo=UTC)
    state = {"ratio": 5.0, "now": observed}
    provider = SimpleNamespace(
        name="test",
        get_capital_flow=lambda code: [
            CapitalFlowDTO(
                code="600000.SH",
                trade_date=date(2026, 8, 31),
                main_net=100_000_000,
                main_net_ratio=state["ratio"],
            )
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_now", lambda: state["now"])

    assert ingest.ingest_capital_flow("600000.SH") == 1
    state["now"] = observed + timedelta(hours=1)
    assert ingest.ingest_capital_flow("600000.SH") == 1
    state["ratio"] = 8.0
    state["now"] = observed + timedelta(days=1)
    assert ingest.ingest_capital_flow("600000.SH") == 1

    with sessions() as session:
        rows = session.execute(
            select(CapitalFlowVintage).order_by(
                CapitalFlowVintage.available_at
            )
        ).scalars().all()
    assert len(rows) == 2
    assert rows[0].vintage != rows[1].vintage
    assert rows[0].fetched_at.replace(tzinfo=UTC) == observed
    assert rows[0].last_seen_at.replace(tzinfo=UTC) == observed + timedelta(
        hours=1
    )

    historical = market.get_capital_flow(
        "600000.SH",
        as_of=observed + timedelta(hours=12),
    )
    current = market.get_capital_flow("600000.SH")
    assert historical["items"][0]["mainNetRatio"] == 5.0
    assert current["items"][0]["mainNetRatio"] == 8.0
    assert datetime.fromisoformat(
        historical["meta"]["asOf"]
    ) <= observed + timedelta(hours=12)
    with pytest.raises(ValueError, match="limit"):
        market.get_capital_flow("600000.SH", limit=0)
    panel = backtest_data.load_pit_auxiliary_panels(
        ["600000.SH"],
        "2026-08-31",
        "2026-09-02",
        capital_flow=True,
    )
    assert len(panel["capital_flow"]["600000.SH"]) == 2
    engine.dispose()
