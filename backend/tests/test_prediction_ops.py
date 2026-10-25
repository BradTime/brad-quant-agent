from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.prediction_ops import PredictionOpsJob
from app.models.user import User
from app.services import prediction_ops


def _database(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    PredictionOpsJob.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(prediction_ops, "SessionLocal", sessions)
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
    return engine, sessions


def test_prediction_ops_enqueue_is_idempotent_and_worker_is_leased(
    monkeypatch,
):
    engine, sessions = _database(monkeypatch)
    scheduled_for = date(2026, 9, 11)
    first = prediction_ops.enqueue(
        job_type="daily_infer",
        scheduled_for=scheduled_for,
        codes=["600000.SH"],
        provider="lightgbm",
        requested_by_user_id="admin-a",
    )
    repeated = prediction_ops.enqueue(
        job_type="daily_infer",
        scheduled_for=scheduled_for,
        codes=["600000.SH"],
        provider="lightgbm",
        requested_by_user_id="admin-a",
    )
    assert repeated["id"] == first["id"]

    claim = prediction_ops._claim()
    assert claim is not None
    assert prediction_ops._claim() is None
    job_id, token = claim
    assert prediction_ops._finish(
        job_id, token, result={"forecastCount": 1}
    )
    with sessions() as session:
        row = session.get(PredictionOpsJob, job_id)
        assert row.status == "completed"
    engine.dispose()


def test_stale_worker_cannot_publish_and_failed_jobs_back_off(
    monkeypatch,
):
    engine, sessions = _database(monkeypatch)
    job = prediction_ops.enqueue(
        job_type="weekly_train",
        scheduled_for=date(2026, 9, 11),
        codes=["600000.SH"],
        provider="lightgbm",
        requested_by_user_id="admin-a",
    )
    old_id, old_token = prediction_ops._claim()
    with sessions.begin() as session:
        row = session.get(PredictionOpsJob, old_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    new_id, new_token = prediction_ops._claim()
    assert new_id == job["id"]
    assert new_token != old_token
    assert not prediction_ops._finish(
        old_id, old_token, result={"status": "validated"}
    )
    assert prediction_ops._finish(
        new_id, new_token, error=ValueError("data unavailable")
    )
    with sessions() as session:
        row = session.get(PredictionOpsJob, new_id)
        assert row.status == "queued"
        assert row.error_code == "ValueError"
    engine.dispose()


def test_process_next_publishes_only_current_claim(monkeypatch):
    engine, sessions = _database(monkeypatch)
    prediction_ops.enqueue(
        job_type="daily_infer",
        scheduled_for=date(2026, 9, 11),
        codes=["600000.SH"],
        provider="lightgbm",
        requested_by_user_id="admin-a",
    )
    monkeypatch.setattr(
        prediction_ops,
        "_execute",
        lambda row, claim_token: {"forecastCount": 1},
    )
    monkeypatch.setattr(
        prediction_ops,
        "_heartbeat",
        lambda *args: nullcontext(),
    )
    assert prediction_ops.process_next() is True
    with sessions() as session:
        row = session.scalar(select(PredictionOpsJob))
        assert row.status == "completed"
    engine.dispose()
