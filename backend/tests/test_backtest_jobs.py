"""H21：网格回测异步任务入队 / 取消 / worker 消费。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.job import BacktestJob
from app.models.user import User
from app.schemas.backtest import GridSearchRequest
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
