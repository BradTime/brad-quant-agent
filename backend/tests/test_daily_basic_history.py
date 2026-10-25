from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.extra import TushareDailyBasic
from app.models.ingestion import DailyBasicHistorySnapshot
from app.models.market import Instrument
from app.services import daily_basic_history


def _raw():
    return {
        "ts_code": "600000.SH",
        "trade_date": "20261023",
        "pe_ttm": 8.5,
        "pb": 0.8,
        "ps_ttm": 1.2,
        "dv_ttm": 4.5,
        "total_mv": 123456.78,
    }


def test_daily_basic_snapshot_normalizes_units_and_is_idempotent(
    monkeypatch,
):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Instrument.__table__.create(engine)
    DailyBasicHistorySnapshot.__table__.create(engine)
    TushareDailyBasic.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(daily_basic_history, "SessionLocal", sessions)
    with sessions.begin() as session:
        session.add(Instrument(code="600000.SH", exchange="SH"))
    kwargs = {
        "raw_rows": [_raw()],
        "codes": ["600000.SH"],
        "start": date(2026, 10, 23),
        "end": date(2026, 10, 23),
        "as_of_date": date(2026, 10, 25),
    }
    first = daily_basic_history.persist_snapshot(**kwargs)
    assert daily_basic_history.persist_snapshot(**kwargs) == first
    with sessions() as session:
        values = daily_basic_history.rows_by_code_date_in_session(
            session,
            snapshot_id=first["id"],
            codes=["600000.SH"],
            start=date(2026, 10, 23),
            end=date(2026, 10, 23),
        )
        stored = session.query(TushareDailyBasic).one()
    assert stored.total_mv == Decimal("1234567800.0000")
    assert stored.available_at == datetime(
        2026, 10, 23, 9, 0, tzinfo=UTC
    ).replace(tzinfo=None)
    assert values["600000.SH"][date(2026, 10, 23)]["peTtm"] == 8.5
    engine.dispose()


def test_daily_basic_preserves_missing_pe():
    row = daily_basic_history.normalize_rows(
        [{**_raw(), "pe_ttm": None}],
        codes=["600000.SH"],
        start=date(2026, 10, 23),
        end=date(2026, 10, 23),
    )[0]
    assert row["pe_ttm"] is None
