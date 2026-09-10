from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.prediction import (
    PredictionForecast,
    PredictionModelRun,
    PredictionPromotionAudit,
)
from app.models.user import User
from app.prediction.features import PredictionExample
from app.services import prediction_registry


def _example() -> PredictionExample:
    return PredictionExample(
        code="600000.SH",
        signal_date=date(2026, 9, 8),
        label_date=date(2026, 9, 9),
        features={
            "return1": 0.01,
            "return5": 0.02,
            "return20": 0.03,
            "volatility20": 0.01,
            "range1": 0.02,
            "amountZ20": 0.1,
            "volumeZ20": 0.1,
        },
        next_return=0.01,
        next_up=1,
    )


@pytest.fixture
def registry_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    PredictionModelRun.__table__.create(engine)
    PredictionForecast.__table__.create(engine)
    PredictionPromotionAudit.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(prediction_registry, "SessionLocal", sessions)
    with sessions.begin() as session:
        session.add(
            User(
                id="user-a",
                email="a@example.com",
                name="A",
                password_hash="x",
            )
        )
    try:
        yield sessions
    finally:
        engine.dispose()


def test_rejected_candidate_cannot_be_promoted(registry_db, monkeypatch):
    monkeypatch.setattr(
        prediction_registry,
        "evaluate_walk_forward",
        lambda *args, **kwargs: {
            "promotionEligible": False,
            "folds": [],
            "regimes": {},
        },
    )
    result = prediction_registry.register_candidate(
        "user-a",
        version="rejected-1",
        provider="lightgbm",
        examples=[_example()],
        regime_by_date={},
        evidence_sha256="e" * 64,
    )
    assert result["status"] == "rejected"
    with pytest.raises(ValueError, match="已存在"):
        prediction_registry.register_candidate(
            "user-a",
            version="rejected-1",
            provider="lightgbm",
            examples=[_example()],
            regime_by_date={},
            evidence_sha256="e" * 64,
        )
    with pytest.raises(ValueError, match="未通过"):
        prediction_registry.promote_candidate(
            result["id"], promoted_by_user_id="user-a"
        )


def test_interrupted_registration_can_fail_closed(
    registry_db,
):
    with registry_db.begin() as session:
        session.add(
            PredictionModelRun(
                id="interrupted",
                user_id="user-a",
                version="interrupted-1",
                provider="lightgbm",
                status="registering",
                feature_schema_version="daily-pit-v1",
                data_sha256="a" * 64,
                artifact_path="/missing/manifest.json",
                artifact_sha256=None,
                metrics_json={
                    "schemaVersion": 1,
                    "payload": {"status": "evaluating"},
                },
                training_start=date(2024, 1, 1),
                training_end=date(2026, 1, 1),
                is_champion=False,
            )
        )
    recovered = prediction_registry.recover_registration("interrupted-1")
    assert recovered["status"] == "failed"


def test_validated_candidate_promotes_and_persists_forecast(
    registry_db, monkeypatch
):
    monkeypatch.setattr(
        prediction_registry,
        "evaluate_walk_forward",
        lambda *args, **kwargs: {
            "promotionEligible": True,
            "folds": [{"passed": True}],
            "regimes": {
                "bull": {"passed": True},
                "bear": {"passed": True},
                "range": {"passed": True},
            },
        },
    )
    fake_model = SimpleNamespace(
        predict=lambda examples: [
            {
                "probabilityUp": 0.6,
                "returnP10": -0.01,
                "returnP50": 0.005,
                "returnP90": 0.02,
            }
            for _ in examples
        ]
    )
    monkeypatch.setattr(
        prediction_registry, "train_prediction_model", lambda *args, **kwargs: fake_model
    )
    monkeypatch.setattr(
        prediction_registry,
        "save_model_bundle",
        lambda *args, **kwargs: {
            "artifactPath": "/trusted/manifest.json",
            "manifestSha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        prediction_registry,
        "verify_model_bundle",
        lambda *args, **kwargs: {"schemaVersion": 2},
    )
    result = prediction_registry.register_candidate(
        "user-a",
        version="candidate-1",
        provider="lightgbm",
        examples=[_example()],
        regime_by_date={},
        evidence_sha256="e" * 64,
    )
    assert result["status"] == "validated"
    monkeypatch.setattr(
        prediction_registry,
        "verify_model_bundle",
        lambda *args, **kwargs: {
            "schemaVersion": 2,
            "version": "candidate-1",
            "provider": "lightgbm",
            "dataSha256": result["dataSha256"],
            "metrics": result["metrics"],
            "promotionEligible": True,
            "artifactStatus": "validated_unregistered",
        },
    )
    monkeypatch.setattr(
        "app.services.evolution.verify_promotion_eligibility",
        lambda session, model: None,
    )
    promoted = prediction_registry.promote_candidate(
        result["id"], promoted_by_user_id="user-a"
    )
    assert promoted["status"] == "champion"

    monkeypatch.setattr(
        prediction_registry, "load_model_bundle", lambda *args, **kwargs: fake_model
    )
    forecasts = prediction_registry.infer_and_store([_example()])
    assert forecasts[0]["probabilityUp"] == 0.6
    stored = prediction_registry.get_prediction("600000.SH")
    assert stored is not None
    assert stored["model"]["version"] == "candidate-1"
    assert (
        prediction_registry.get_prediction(
            "600000.SH", as_of=date(2026, 9, 8)
        )
        is None
    )
    with registry_db() as session:
        assert session.execute(select(PredictionForecast)).scalars().one()
        audit = session.execute(
            select(PredictionPromotionAudit)
        ).scalars().one()
        assert audit.promoted_by_user_id == "user-a"
        assert audit.promoted_by_user_id_snapshot == "user-a"
