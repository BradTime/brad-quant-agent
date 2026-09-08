import exchange_calendars as xcals
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.market import DailyBar, Instrument, InstrumentStatusHistory
from app.models.universe import UniverseMembershipDaily
from app.services import universe_membership


def test_materialized_full_a_universe_is_pit_filtered_and_queryable(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Instrument.__table__,
            DailyBar.__table__,
            InstrumentStatusHistory.__table__,
            UniverseMembershipDaily.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(universe_membership, "SessionLocal", sessions)
    calendar = xcals.get_calendar("XSHG")
    trading_days = [
        timestamp.date()
        for timestamp in calendar.sessions_in_range(
            "2024-01-01", "2024-12-31"
        )
    ][-140:]
    as_of = trading_days[-1]
    with sessions.begin() as session:
        for code in ("600000.SH", "000001.SZ"):
            session.add(
                Instrument(
                    code=code,
                    name=code,
                    exchange=code[-2:],
                    security_type="stock",
                    list_date=trading_days[-130],
                    status="listed",
                )
            )
            session.add(
                InstrumentStatusHistory(
                    code=code,
                    start_date=trading_days[-130],
                    end_date=None,
                    name=code,
                    status_type="normal",
                    source="test",
                )
            )
            for day in trading_days:
                amount = 60_000_000 if code == "600000.SH" else 40_000_000
                session.add(
                    DailyBar(
                        code=code,
                        trade_date=day,
                        open=10,
                        high=10,
                        low=10,
                        close=10,
                        volume=1_000_000,
                        amount=amount,
                        source="test",
                    )
                )

    summary = universe_membership.build_for_date(as_of)

    assert summary["total"] == 2
    assert summary["eligible"] == 1
    assert universe_membership.eligible_codes(as_of) == ["600000.SH"]
    excluded = universe_membership.membership(as_of, "000001.SZ")
    assert excluded is not None
    assert excluded["eligible"] is False
    assert "low_liquidity" in excluded["reasons"]
    assert universe_membership.eligible_map(
        ["999999.SH"], as_of, as_of
    ) == {as_of.isoformat(): ()}
    repeated = universe_membership.build_for_date(as_of)
    assert repeated["reused"] is True
    assert repeated["eligible"] == 1
    engine.dispose()
