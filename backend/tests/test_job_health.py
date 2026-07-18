"""调度任务健康登记与 /ready 探针。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import job_health


def setup_function() -> None:
    job_health.reset_for_tests()


def test_tracked_records_success_and_failure():
    @job_health.tracked("demo_ok")
    def ok() -> str:
        return "x"

    @job_health.tracked("demo_fail")
    def boom() -> None:
        raise RuntimeError("nope")

    assert ok() == "x"
    snap = job_health.snapshot()
    assert snap["demo_ok"]["consecutiveFailures"] == 0
    assert snap["demo_ok"]["runs"] == 1

    try:
        boom()
    except RuntimeError:
        pass
    snap = job_health.snapshot()
    assert snap["demo_fail"]["consecutiveFailures"] == 1
    assert snap["demo_fail"]["lastError"] == "RuntimeError"


def test_is_healthy_ignores_unrun_jobs_and_flags_failures():
    ok, reasons = job_health.is_healthy(
        required_jobs=["missing"],
        max_consecutive_failures=3,
    )
    assert ok is True
    assert reasons == []

    job_health.record_failure("refresh_quotes", "Timeout")
    job_health.record_failure("refresh_quotes", "Timeout")
    job_health.record_failure("refresh_quotes", "Timeout")
    ok, reasons = job_health.is_healthy(
        required_jobs=["refresh_quotes"],
        max_consecutive_failures=3,
    )
    assert ok is False
    assert any("consecutive_failures" in r for r in reasons)


def test_ready_ok_when_scheduler_disabled(monkeypatch):
    from app.api import health as health_api
    from app.core.config import settings

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(health_api, "engine", _Engine())
    monkeypatch.setattr(settings, "enable_scheduler", False)
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["database"] == "ok"
    assert body["data"]["schedulerEnabled"] is False
