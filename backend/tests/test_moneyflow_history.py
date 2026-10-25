from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.extra import TushareMoneyflowDaily
from app.models.ingestion import MoneyflowHistorySnapshot
from app.models.market import Instrument
from app.services import moneyflow_history


@pytest.fixture
def moneyflow_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Instrument.__table__.create(engine)
    MoneyflowHistorySnapshot.__table__.create(engine)
    TushareMoneyflowDaily.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(moneyflow_history, "SessionLocal", sessions)
    with sessions.begin() as session:
        session.add(Instrument(code="600000.SH", exchange="SH"))
    try:
        yield sessions
    finally:
        engine.dispose()


def _raw():
    return {
        "ts_code": "600000.SH",
        "trade_date": "20261023",
        "buy_sm_amount": 10,
        "sell_sm_amount": 8,
        "buy_md_amount": 20,
        "sell_md_amount": 18,
        "buy_lg_amount": 30,
        "sell_lg_amount": 25,
        "buy_elg_amount": 40,
        "sell_elg_amount": 35,
        "net_mf_amount": 14,
    }


def test_moneyflow_normalization_converts_ten_thousand_yuan_and_time():
    row = moneyflow_history.normalize_rows(
        [_raw()],
        codes=["600000.SH"],
        start=date(2026, 10, 23),
        end=date(2026, 10, 23),
    )[0]
    assert row["net_amount"] == Decimal("140000.0000")
    assert row["large_net_amount"] == Decimal("50000.0000")
    assert row["extra_large_net_amount"] == Decimal("50000.0000")
    assert row["available_at"] == datetime(
        2026, 10, 23, 11, 0, tzinfo=UTC
    )


def test_moneyflow_snapshot_is_idempotent_and_queryable(moneyflow_db):
    kwargs = {
        "raw_rows": [_raw()],
        "codes": ["600000.SH"],
        "start": date(2026, 10, 23),
        "end": date(2026, 10, 23),
        "as_of_date": date(2026, 10, 25),
    }
    first = moneyflow_history.persist_snapshot(**kwargs)
    assert moneyflow_history.persist_snapshot(**kwargs) == first
    with moneyflow_db() as session:
        snapshot_id = moneyflow_history.latest_snapshot_id(
            session,
            codes=["600000.SH"],
            start=date(2026, 10, 23),
            end=date(2026, 10, 23),
        )
        values = moneyflow_history.rows_by_code_date_in_session(
            session,
            snapshot_id=snapshot_id,
            codes=["600000.SH"],
            start=date(2026, 10, 23),
            end=date(2026, 10, 23),
        )
    assert values["600000.SH"][date(2026, 10, 23)] == {
        "netAmount": 140000.0,
        "largeNetAmount": 100000.0,
    }


def test_moneyflow_rejects_conflicting_duplicate():
    changed = {**_raw(), "net_mf_amount": 15}
    with pytest.raises(ValueError, match="重复冲突"):
        moneyflow_history.normalize_rows(
            [_raw(), changed],
            codes=["600000.SH"],
            start=date(2026, 10, 23),
            end=date(2026, 10, 23),
        )
