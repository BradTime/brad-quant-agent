from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.data import Bar
from app.core.json_payload import dump_envelope
from app.models.evolution import (
    EvolutionObservation,
    EvolutionProgram,
    EvolutionSignalCommitment,
    EvolutionTransition,
)
from app.models.prediction import PredictionModelRun
from app.models.universe import UniverseSnapshotDaily
from app.models.user import User
from app.services import evolution


def _bar(code: str, day: date, price: float, *, volume: float = 1_000_000):
    return Bar(
        code=code,
        date=day,
        open=price,
        high=price * 1.02,
        low=price * 0.98,
        close=price * 1.01,
        volume=volume,
        amount=volume * price,
        previous_close=price,
        limit_ratio=0.10,
    )


def test_rebalance_enforces_lots_capacity_costs_and_t_plus_one():
    signal = date(2026, 9, 9)
    label = date(2026, 9, 10)
    cash, holdings, equity, fills = evolution._rebalance(
        cash=200_000,
        holdings={},
        targets={"600000.SH": 0.2},
        signal_bars={"600000.SH": _bar("600000.SH", signal, 10)},
        label_bars={"600000.SH": _bar("600000.SH", label, 10)},
    )
    assert holdings["600000.SH"] % 100 == 0
    assert holdings["600000.SH"] <= 10_000
    assert cash < 200_000
    assert equity > 0
    assert fills[0]["side"] == "buy"

    _, reduced, _, sell_fills = evolution._rebalance(
        cash=cash,
        holdings=holdings,
        targets={"600000.SH": 0.0},
        signal_bars={"600000.SH": _bar("600000.SH", label, 10)},
        label_bars={
            "600000.SH": _bar(
                "600000.SH", date(2026, 9, 11), 10
            )
        },
    )
    assert reduced == {}
    assert sell_fills[0]["side"] == "sell"


def test_enrolled_challenger_uses_server_daily_evidence(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        PredictionModelRun.__table__,
        UniverseSnapshotDaily.__table__,
        EvolutionProgram.__table__,
        EvolutionSignalCommitment.__table__,
        EvolutionObservation.__table__,
        EvolutionTransition.__table__,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(evolution, "SessionLocal", sessions)
    signal = date(2026, 9, 9)
    label = date(2026, 9, 10)
    with sessions.begin() as session:
        session.add(
            User(
                id="admin-a",
                email="admin@example.com",
                name="Admin",
                password_hash="x",
                role="admin",
            )
        )
        session.add(
            PredictionModelRun(
                id="candidate-1",
                user_id="admin-a",
                version="candidate-v1",
                provider="lightgbm",
                status="validated",
                feature_schema_version="daily-pit-v1",
                data_sha256="d" * 64,
                artifact_path="/trusted/manifest.json",
                artifact_sha256="a" * 64,
                metrics_json=dump_envelope(
                    {"promotionEligible": True}
                ),
                training_start=date(2023, 1, 1),
                training_end=date(2026, 1, 1),
                is_champion=False,
            )
        )
        session.add(
            UniverseSnapshotDaily(
                trade_date=signal,
                rules_version="pit-universe-v3",
                member_count=1,
                eligible_count=1,
                advancing_count=1,
                declining_count=1,
                filters_sha256="f" * 64,
                membership_sha256="m" * 64,
            )
        )
    monkeypatch.setattr(
        evolution.universe_membership,
        "eligible_codes",
        lambda day: ["600000.SH"],
    )
    enrolled = evolution.enroll(
        "candidate-1",
        codes=["600000.SH"],
        created_by_user_id="admin-a",
    )
    monkeypatch.setattr(
        evolution,
        "_next_session",
        lambda day: label if day == signal else date(2026, 9, 11),
    )
    monkeypatch.setattr(
        evolution,
        "_forecast_rows",
        lambda model_id, day, codes: [
            {
                "code": "600000.SH",
                "probabilityUp": 0.7,
                "returnP10": -0.01,
                "returnP50": 0.02,
                "returnP90": 0.05,
                "featureSha256": "z" * 64,
                "features": {"return_1": 0.01},
            }
        ],
    )
    monkeypatch.setattr(
        evolution.prediction_training,
        "build_inference_features_from_database",
        lambda signal_date, codes: [
            SimpleNamespace(
                code="600000.SH",
                features={"return_1": 0.01},
            )
        ],
    )
    monkeypatch.setattr(
        evolution,
        "_exact_bars",
        lambda code, start, end: (
            _bar(code, start, 10),
            _bar(code, end, 10),
        ),
    )
    monkeypatch.setattr(
        evolution,
        "_single_bar",
        lambda code, day: _bar(code, day, 10),
    )
    monkeypatch.setattr(
        evolution.industry_history,
        "industries_asof_in_session",
        lambda session, codes, day: {"600000.SH": "银行"},
    )
    monkeypatch.setattr(
        evolution.authoritative_allocation,
        "_authoritative_regime",
        lambda session, day: {"regime": "bull"},
    )
    monkeypatch.setattr(
        evolution.industry_history,
        "industry_evidence_asof_in_session",
        lambda session, codes, day: {
            "600000.SH": {
                "industry": "银行",
                "vintage": "v1",
                "availableAt": "2026-09-09T08:00:00+00:00",
            }
        },
    )
    commitment = evolution.commit_signal(
        enrolled["id"], signal_date=signal
    )
    assert commitment["committed"] is True
    with sessions.begin() as session:
        session.add(
            UniverseSnapshotDaily(
                trade_date=label,
                rules_version="pit-universe-v3",
                member_count=1,
                eligible_count=1,
                advancing_count=1,
                declining_count=1,
                filters_sha256="f" * 64,
                membership_sha256="n" * 64,
                computed_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        )

    result = evolution.evaluate_day(
        enrolled["id"], signal_date=signal
    )

    assert result["simulationSessions"] == 1
    assert result["executionEnabled"] is False
    with sessions() as session:
        observation = session.scalar(select(EvolutionObservation))
        assert observation.signal_date == signal
        assert observation.label_date == label
    engine.dispose()
