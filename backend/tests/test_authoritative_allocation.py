from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.data import Bar
from app.models.prediction import (
    PortfolioAllocationDecision,
    PortfolioRiskProfile,
    PredictionModelRun,
    RegimeSnapshot,
)
from app.models.universe import UniverseSnapshotDaily
from app.models.user import User
from app.services import authoritative_allocation


def test_authoritative_preview_uses_only_server_owned_inputs(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        PredictionModelRun.__table__,
        UniverseSnapshotDaily.__table__,
        PortfolioRiskProfile.__table__,
        RegimeSnapshot.__table__,
        PortfolioAllocationDecision.__table__,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(authoritative_allocation, "SessionLocal", sessions)
    as_of = date(2026, 9, 9)
    with sessions.begin() as session:
        session.add(
            User(
                id="user-a",
                email="a@example.com",
                name="A",
                password_hash="x",
            )
        )
        session.add(
            PredictionModelRun(
                id="model-1",
                user_id="user-a",
                version="champion-1",
                provider="lightgbm",
                status="champion",
                feature_schema_version="daily-pit-v1",
                data_sha256="a" * 64,
                artifact_path="/trusted/manifest.json",
                artifact_sha256="b" * 64,
                metrics_json={"schemaVersion": 1, "payload": {}},
                training_start=date(2023, 1, 1),
                training_end=date(2026, 1, 1),
                is_champion=True,
            )
        )
        session.add(
            UniverseSnapshotDaily(
                trade_date=as_of,
                rules_version="pit-universe-v3",
                member_count=100,
                eligible_count=80,
                advancing_count=60,
                declining_count=20,
                filters_sha256="c" * 64,
                membership_sha256="d" * 64,
            )
        )
    monkeypatch.setattr(
        authoritative_allocation.trading,
        "get_portfolio_snapshot_in_session",
        lambda session, user_id, valuation_date=None: (
            {
                "cash": 100_000,
                "frozenCash": 0,
                "initialCash": 200_000,
                "marketValue": 100_000,
                "totalAssets": 200_000,
            },
            [],
        ),
    )
    monkeypatch.setattr(
        authoritative_allocation.industry_history,
        "industries_asof_in_session",
        lambda session, codes, day: {code: "银行" for code in codes},
    )
    monkeypatch.setattr(
        authoritative_allocation.prediction_registry,
        "get_prediction_in_session",
        lambda session, code, as_of=None: {
            "code": code,
            "signalDate": as_of.isoformat(),
            "probabilityUp": 0.6,
            "returnInterval80": {
                "low": -0.02,
                "median": 0.01,
                "high": 0.03,
            },
            "model": {"runId": "model-1"},
        },
    )
    benchmark_start = as_of - timedelta(days=59)
    monkeypatch.setattr(
        authoritative_allocation,
        "_load_hfq_bars_in_session",
        lambda session, code, start, end: (
            [
                Bar(
                    code="000300.SH",
                    date=benchmark_start + timedelta(days=index),
                    open=100 + index,
                    high=100 + index,
                    low=100 + index,
                    close=100 + index,
                    volume=1,
                    amount=1,
                )
                for index in range(60)
            ],
            "full",
        ),
    )
    monkeypatch.setattr(
        authoritative_allocation,
        "_ingestion_run_quality_in_session",
        lambda *args, **kwargs: None,
    )

    result = authoritative_allocation.preview(
        "user-a",
        requested_codes=["600000.SH"],
        as_of=as_of,
    )

    assert result["authoritative"] is True
    assert result["executionApproved"] is False
    assert result["modelRunId"] == "model-1"
    with sessions() as session:
        assert session.execute(select(RegimeSnapshot)).scalars().one()
        assert (
            session.execute(
                select(PortfolioAllocationDecision)
            ).scalars().one()
        )
    engine.dispose()
