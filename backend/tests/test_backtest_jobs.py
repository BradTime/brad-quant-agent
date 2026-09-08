"""H21：网格回测异步任务入队 / 取消 / worker 消费。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.job import BacktestJob
from app.models.user import User
from app.schemas.backtest import FullABacktestRequest, GridSearchRequest
from app.services import backtest_jobs, backtest_run


@pytest.fixture
def job_env(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[BacktestJob.__table__, User.__table__])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(backtest_jobs, "SessionLocal", sessions)
    monkeypatch.setattr(backtest_run, "SessionLocal", sessions)
    try:
        yield sessions
    finally:
        engine.dispose()


def _grid_req(**overrides) -> GridSearchRequest:
    base = {
        "strategyType": "dual_ma",
        "paramGrid": {"fast": [5, 10], "slow": [20]},
        "codes": ["600000.SH"],
        "start": date(2024, 1, 1),
        "end": date(2024, 6, 30),
        "initialCapital": 100_000,
        "slippage": 0.001,
        "engine": "native",
        "sortBy": "sharpeRatio",
        "frequency": "1d",
    }
    base.update(overrides)
    return GridSearchRequest.model_validate(base)


def _full_a_req() -> FullABacktestRequest:
    return FullABacktestRequest.model_validate(
        {
            "strategyType": "xs_momentum",
            "params": {"lookback": 60, "topN": 3, "target": 0.95},
            "start": "2024-01-01",
            "end": "2024-06-30",
        }
    )


def test_enqueue_and_cancel_queued(job_env) -> None:
    job = backtest_jobs.enqueue_grid("user-1", _grid_req())
    assert job["status"] == "queued"
    assert job["progressTotal"] == 2
    cancelled = backtest_jobs.request_cancel("user-1", job["id"])
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"


def test_worker_respects_cancel_during_run(job_env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_grid(*_a, cancel_check=None, on_progress=None, **_k):
        calls["n"] += 1
        if on_progress:
            on_progress(0, 2)
        if cancel_check and cancel_check():
            return {"results": [], "cancelled": True, "best": None, "engine": "native"}
        return {
            "results": [{"params": {"fast": 5}, "metrics": {"sharpeRatio": 1.0}}],
            "best": {"params": {"fast": 5}, "metrics": {"sharpeRatio": 1.0}},
            "engine": "native",
            "sortBy": "sharpeRatio",
            "truncated": False,
        }

    monkeypatch.setattr(backtest_run, "grid_search", fake_grid)
    job = backtest_jobs.enqueue_grid("user-1", _grid_req())
    backtest_jobs.request_cancel("user-1", job["id"])
    # queued cancel already terminal
    assert not backtest_jobs.worker_loop_once()


def test_worker_completes_job(job_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backtest_run,
        "grid_search",
        lambda *a, **k: {
            "results": [{"params": {"fast": 5}, "metrics": {"sharpeRatio": 1.2}}],
            "best": {"params": {"fast": 5}, "metrics": {"sharpeRatio": 1.2}},
            "engine": "native",
            "sortBy": "sharpeRatio",
            "truncated": False,
        },
    )
    job = backtest_jobs.enqueue_grid("user-1", _grid_req())
    assert backtest_jobs.worker_loop_once() is True
    done = backtest_jobs.get_job("user-1", job["id"])
    assert done is not None
    assert done["status"] == "completed"
    assert done["result"]["best"]["metrics"]["sharpeRatio"] == 1.2


def test_full_a_job_is_unique_cancel_aware_and_completes(
    job_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = backtest_jobs.enqueue_full_a("user-1", _full_a_req())
    with pytest.raises(ValueError, match="已有全 A"):
        backtest_jobs.enqueue_full_a("user-1", _full_a_req())

    def fake_run(
        user_id,
        req,
        *,
        cancel_check,
        on_progress,
        job_id,
        claim_token,
    ):
        assert job_id == first["id"]
        assert claim_token
        assert not cancel_check()
        on_progress(1, 1)
        return {
            "id": "run-1",
            "status": "completed",
            "strategyType": req.strategyType,
        }

    monkeypatch.setattr(backtest_run, "run_full_a_and_save", fake_run)
    assert backtest_jobs.worker_loop_once()
    done = backtest_jobs.get_job("user-1", first["id"])
    assert done is not None
    assert done["status"] == "completed"
    assert done["progressDone"] == 1


def test_full_a_job_preserves_running_cancellation(
    job_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = backtest_jobs.enqueue_full_a("user-1", _full_a_req())
    monkeypatch.setattr(
        backtest_run,
        "run_full_a_and_save",
        lambda *args, **kwargs: {
            "cancelled": True,
            "progressDone": 2,
            "progressTotal": 10,
        },
    )
    assert backtest_jobs.worker_loop_once()
    done = backtest_jobs.get_job("user-1", job["id"])
    assert done is not None
    assert done["status"] == "cancelled"


def test_stale_running_job_is_reclaimed(job_env) -> None:
    job = backtest_jobs.enqueue_full_a("user-1", _full_a_req())
    with job_env.begin() as session:
        row = session.get(BacktestJob, job["id"])
        row.status = "running"
        row.updated_at = datetime.now(UTC) - timedelta(hours=1)
    claimed = backtest_jobs.claim_next_job()
    assert claimed is not None
    assert claimed.id == job["id"]
    assert claimed.status == "running"


def test_finish_cannot_overwrite_concurrent_cancellation(job_env) -> None:
    job = backtest_jobs.enqueue_full_a("user-1", _full_a_req())
    claimed = backtest_jobs.claim_next_job()
    assert claimed is not None
    cancelled = backtest_jobs.request_cancel("user-1", job["id"])
    assert cancelled is not None and cancelled["cancelRequested"] is True

    backtest_jobs._finish(
        job["id"],
        claimed.claim_token,
        status="completed",
        result={"id": "should-not-win"},
    )

    final = backtest_jobs.get_job("user-1", job["id"])
    assert final is not None
    assert final["status"] == "cancelled"


def test_reclaimed_job_rejects_stale_worker_heartbeat_and_finish(
    job_env,
) -> None:
    job = backtest_jobs.enqueue_full_a("user-1", _full_a_req())
    first = backtest_jobs.claim_next_job()
    assert first is not None and first.claim_token
    with job_env.begin() as session:
        row = session.get(BacktestJob, job["id"])
        row.updated_at = datetime.now(UTC) - timedelta(hours=1)
    second = backtest_jobs.claim_next_job()
    assert second is not None and second.claim_token
    assert second.claim_token != first.claim_token

    backtest_jobs._set_progress(
        job["id"], first.claim_token, 99, 100
    )
    backtest_jobs._finish(
        job["id"],
        first.claim_token,
        status="completed",
        result={"stale": True},
    )

    current = backtest_jobs.get_job("user-1", job["id"])
    assert current is not None
    assert current["status"] == "running"
    assert current["progressDone"] == 0
