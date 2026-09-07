"""H4：DAY TIF / trade_date 隔夜挂单撤销（SQLite，不依赖 Postgres）。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.services import trading


@pytest.fixture
def trading_sqlite(monkeypatch: pytest.MonkeyPatch):
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
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(trading, "SessionLocal", sessions)
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


def test_place_order_records_day_tif_and_trade_date(trading_sqlite, monkeypatch):
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3))
    uid = uuid4().hex
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["status"] == "pending"
    assert order["tif"] == "DAY"
    assert order["tradeDate"] == "2024-01-03"


def test_matcher_settles_stale_day_order_before_fill(trading_sqlite, monkeypatch):
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 2))
    uid = uuid4().hex
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["status"] == "pending"

    with trading.SessionLocal() as session:
        account = session.get(SimAccount, uid)
        account.last_settle_date = date(2024, 1, 2)
        session.commit()

    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3))
    monkeypatch.setattr(
        trading,
        "_execution_snapshot",
        lambda _code: {"price": 8.0, "yesterdayClose": 8.0, "executable": True},
    )
    assert trading.try_match_pending() == 0
    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "cancelled"
    assert trading.get_account(uid)["frozenCash"] == 0.0


def test_eod_settle_cancels_without_user_visit(trading_sqlite, monkeypatch):
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 2))
    uid = uuid4().hex
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)

    with trading.SessionLocal() as session:
        account = session.get(SimAccount, uid)
        account.last_settle_date = date(2024, 1, 2)
        session.commit()

    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3))
    assert trading.settle_all_accounts() == 1
    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "cancelled"
    assert saved["reason"] == "日终未成交，自动撤销"


def test_same_day_pending_survives_eod_settle(trading_sqlite, monkeypatch):
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3))
    uid = uuid4().hex
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["tradeDate"] == "2024-01-03"

    assert trading.settle_all_accounts() == 1
    with trading.SessionLocal() as session:
        row = session.scalar(select(SimOrder).where(SimOrder.id == order["id"]))
        assert row is not None
        assert row.status == "pending"
