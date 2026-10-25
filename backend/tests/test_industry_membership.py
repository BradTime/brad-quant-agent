from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.ingestion import IndustryMembershipSnapshot
from app.models.market import Instrument, InstrumentIndustryMembershipHistory
from app.services import industry_membership


@pytest.fixture
def industry_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Instrument.__table__.create(engine)
    IndustryMembershipSnapshot.__table__.create(engine)
    InstrumentIndustryMembershipHistory.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(industry_membership, "SessionLocal", sessions)
    with sessions.begin() as session:
        session.add_all(
            [
                Instrument(code="600000.SH", exchange="SH"),
                Instrument(code="000001.SZ", exchange="SZ"),
            ]
        )
    try:
        yield sessions
    finally:
        engine.dispose()


def _classes():
    return [
        {
            "index_code": f"801{index:03d}.SI",
            "industry_name": f"行业{index}",
        }
        for index in range(31)
    ]


def test_history_clamps_sw2021_floor_and_merges_same_industry():
    rows, source_count, unknown_count = industry_membership.normalize_history(
        [
            {
                "ts_code": "600000.SH",
                "l1_code": "801000.SI",
                "l1_name": "行业0",
                "in_date": "20000101",
                "out_date": "20220101",
            },
            {
                "ts_code": "600000.SH",
                "l1_code": "801000.SI",
                "l1_name": "行业0",
                "in_date": "20220102",
                "out_date": None,
            },
        ],
        known_codes={"600000.SH"},
    )
    assert source_count == 2
    assert unknown_count == 0
    assert len(rows) == 1
    assert rows[0]["effective_from"] == date(2021, 12, 13)
    assert rows[0]["effective_to"] is None


def test_history_rejects_overlapping_different_industries():
    with pytest.raises(ValueError, match="重叠"):
        industry_membership.normalize_history(
            [
                {
                    "ts_code": "600000.SH",
                    "l1_code": "801000.SI",
                    "l1_name": "行业0",
                    "in_date": "20211213",
                    "out_date": "20220105",
                },
                {
                    "ts_code": "600000.SH",
                    "l1_code": "801001.SI",
                    "l1_name": "行业1",
                    "in_date": "20220105",
                    "out_date": None,
                },
            ],
            known_codes={"600000.SH"},
        )


def test_snapshot_is_idempotent_and_supports_effective_date_lookup(
    industry_db,
):
    raw = [
        {
            "ts_code": "600000.SH",
            "l1_code": "801000.SI",
            "l1_name": "行业0",
            "in_date": "20000101",
            "out_date": "20221231",
        },
        {
            "ts_code": "600000.SH",
            "l1_code": "801001.SI",
            "l1_name": "行业1",
            "in_date": "20230101",
            "out_date": None,
        },
    ]
    first = industry_membership.persist_snapshot(
        classifications=_classes(),
        raw_rows=raw,
        as_of_date=date(2026, 10, 25),
    )
    second = industry_membership.persist_snapshot(
        classifications=_classes(),
        raw_rows=raw,
        as_of_date=date(2026, 10, 25),
    )
    assert second == first
    with industry_db.begin() as session:
        snapshot = session.get(IndustryMembershipSnapshot, first["id"])
        snapshot.fetched_at = datetime(2026, 10, 25, 4, tzinfo=UTC)
    with industry_db() as session:
        with pytest.raises(ValueError, match="缺少"):
            industry_membership.latest_snapshot_id(
                session, available_on=date(2026, 10, 24)
            )
        assert (
            industry_membership.latest_snapshot_id(
                session, available_on=date(2026, 10, 25)
            )
            == first["id"]
        )
        assert industry_membership.industries_asof_in_session(
            session,
            ["600000.SH"],
            date(2022, 6, 1),
            snapshot_id=first["id"],
        ) == {"600000.SH": "行业0"}
        assert industry_membership.industries_asof_in_session(
            session,
            ["600000.SH"],
            date(2023, 6, 1),
            snapshot_id=first["id"],
        ) == {"600000.SH": "行业1"}
        with pytest.raises(ValueError, match="缺少历史行业"):
            industry_membership.industries_asof_in_session(
                session,
                ["000001.SZ"],
                date(2023, 6, 1),
                snapshot_id=first["id"],
            )
