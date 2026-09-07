"""Dashboard 聚合：接真实模拟账户 / 持仓 / 成交（SQLite）。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db.base import Base
from app.main import app
from app.models.strategy import Strategy
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.services import dashboard, strategy, trading


@pytest.fixture
def dashboard_sqlite(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            SimAccount.__table__,
            SimPosition.__table__,
            SimOrder.__table__,
            SimTrade.__table__,
            Strategy.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(trading, "SessionLocal", sessions)
    monkeypatch.setattr(strategy, "SessionLocal", sessions)
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 10.0,
            "yesterdayClose": 10.0,
            "executable": True,
        },
    )
    monkeypatch.setattr(trading.market, "get_instrument_name", lambda code: code)
    monkeypatch.setattr(
        trading.market,
        "get_instrument_list_date",
        lambda _code: date(1999, 1, 1),
        raising=False,
    )
    try:
        yield sessions
    finally:
        engine.dispose()


def test_get_stats_reflects_sim_account(dashboard_sqlite):
    uid = uuid4().hex
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    stats = dashboard.get_stats(uid)
    assert stats["initialCash"] == 1_000_000.0
    assert stats["totalAssets"] < 1_000_000.0
    assert stats["marketValue"] == 1000.0
    assert stats["runningStrategies"] == 0


def test_position_distribution_and_recent_trades(dashboard_sqlite):
    uid = uuid4().hex
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    dist = dashboard.position_distribution(uid)
    assert len(dist) == 1
    assert dist[0]["symbol"] == "600000.SH"
    assert dist[0]["percent"] == 100.0

    trades = dashboard.recent_trades(uid, limit=5)
    assert len(trades) == 1
    assert trades[0]["side"] == "buy"
    assert trades[0]["quantity"] == 100


def test_return_curve_ends_at_total_assets(dashboard_sqlite):
    uid = uuid4().hex
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    curve = dashboard.return_curve(uid, days=30)
    assert curve
    assert curve[-1]["value"] == dashboard.get_stats(uid)["totalAssets"]


def test_dashboard_api_requires_auth_and_returns_real_data(dashboard_sqlite):
    uid = uuid4().hex
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uid)
    client = TestClient(app)
    try:
        trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
        stats = client.get("/api/v1/dashboard/stats")
        assert stats.status_code == 200
        body = stats.json()["data"]
        assert body["totalAssets"] > 0
        assert body["marketValue"] == 1000.0

        dist = client.get("/api/v1/dashboard/position-distribution")
        assert dist.status_code == 200
        assert dist.json()["data"][0]["symbol"] == "600000.SH"

        trades = client.get("/api/v1/dashboard/recent-trades?limit=5")
        assert trades.status_code == 200
        assert len(trades.json()["data"]) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
