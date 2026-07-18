"""H17：JSON 信封 schemaVersion、损坏态、遗留裸 JSON 升级。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.json_payload import (
    CURRENT_SCHEMA_VERSION,
    JsonCorruptError,
    dump_envelope,
    load_envelope,
)
from app.db.base import Base
from app.models.backtest import BacktestRun
from app.models.brief import MorningBrief
from app.models.research import ResearchReport
from app.models.strategy import Strategy
from app.services import backtest_run, brief, strategy


def test_dump_load_roundtrip_and_legacy_upgrade():
    env = dump_envelope({"a": 1})
    assert env["schemaVersion"] == CURRENT_SCHEMA_VERSION
    assert load_envelope(env, expect="dict") == {"a": 1}
    # legacy bare object
    assert load_envelope({"a": 1}, expect="dict") == {"a": 1}
    # legacy bare list
    assert load_envelope([1, 2], expect="list") == [1, 2]


def test_corrupt_text_raises():
    with pytest.raises(JsonCorruptError):
        load_envelope("{not-json", expect="dict", field="metrics_json")


def test_wrong_payload_type_raises():
    with pytest.raises(JsonCorruptError):
        load_envelope(dump_envelope([1, 2]), expect="dict", field="metrics_json")


@pytest.fixture
def json_sqlite(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Strategy.__table__,
            BacktestRun.__table__,
            MorningBrief.__table__,
            ResearchReport.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(strategy, "SessionLocal", sessions)
    monkeypatch.setattr(backtest_run, "SessionLocal", sessions)
    monkeypatch.setattr(brief, "SessionLocal", sessions)
    try:
        yield sessions
    finally:
        engine.dispose()


def test_strategy_corrupt_params_surface_data_corrupt(json_sqlite):
    uid = uuid4().hex
    created = strategy.create_strategy(
        uid, name="t", description="", builtin_type="dual_ma", params={"fast": 5, "slow": 20}
    )
    with strategy.SessionLocal() as session:
        row = session.get(Strategy, created["id"])
        assert row is not None
        row.params_json = "not-json{{"  # type: ignore[assignment]
        session.commit()

    view = strategy.get_strategy(uid, created["id"])
    assert view is not None
    assert view["status"] == "data_corrupt"
    assert view["params"] is None
    assert "corrupt" in (view.get("error") or "")


def test_backtest_corrupt_metrics_not_fake_zeros(json_sqlite):
    run_id = uuid4().hex
    with backtest_run.SessionLocal() as session:
        session.add(
            BacktestRun(
                id=run_id,
                user_id="u1",
                strategy_type="dual_ma",
                status="completed",
                config_json=dump_envelope({"strategyType": "dual_ma", "params": {}}),
                metrics_json="{bad",  # type: ignore[arg-type]
                equity_json=dump_envelope([]),
                trades_json=dump_envelope([]),
                data_quality_json=dump_envelope({}),
                engine="native",
            )
        )
        session.commit()

    view = backtest_run.get_run("u1", run_id)
    assert view is not None
    assert view["status"] == "data_corrupt"
    assert view["metrics"] is None
    assert view["config"]["strategyType"] == "dual_ma"


def test_brief_legacy_bare_snapshot_still_loads(json_sqlite, monkeypatch):
    monkeypatch.setattr(brief, "_today", lambda: date(2024, 6, 1))
    brief_id = uuid4().hex
    bare = {
        "engine": "single",
        "pack": {"indices": []},
        "agentTrace": [{"node": "x"}],
    }
    with brief.SessionLocal() as session:
        session.add(
            MorningBrief(
                id=brief_id,
                user_id="u1",
                trade_date=date(2024, 6, 1),
                status="ready",
                title="t",
                content="正文",
                data_pack_json=bare,  # legacy unwrapped
            )
        )
        session.commit()

    view = brief.get_brief(brief_id, "u1")
    assert view is not None
    assert view["status"] == "ready"
    assert view["dataPack"] == {"indices": []}
    assert view["agentTrace"][0]["node"] == "x"


def test_brief_corrupt_pack_marks_data_corrupt(json_sqlite):
    brief_id = uuid4().hex
    with brief.SessionLocal() as session:
        session.add(
            MorningBrief(
                id=brief_id,
                user_id="u1",
                trade_date=date(2024, 6, 1),
                status="ready",
                title="t",
                content="正文",
                data_pack_json="{{",  # type: ignore[arg-type]
            )
        )
        session.commit()

    view = brief.get_brief(brief_id, "u1")
    assert view is not None
    assert view["status"] == "data_corrupt"
    assert view["dataPack"] is None
