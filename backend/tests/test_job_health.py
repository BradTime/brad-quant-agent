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


def test_api_readiness_does_not_require_worker_owned_scheduler(monkeypatch):
    from app.api import health as health_api
    from app.core import redis_client
    from app.core.config import settings
    from app.services import scheduler
    from app.ws import redis_bridge

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
    monkeypatch.setattr(settings, "enable_scheduler", True)
    monkeypatch.setattr(settings, "process_role", "api")
    monkeypatch.setattr(settings, "redis_url", "redis://test")
    monkeypatch.setattr(settings, "readiness_startup_grace_seconds", 10_000)
    monkeypatch.setattr(scheduler, "scheduler_running", lambda: False)
    monkeypatch.setattr(redis_client, "status", lambda: {"ok": True})
    monkeypatch.setattr(redis_bridge, "running", lambda: True)
    monkeypatch.setattr(
        redis_client,
        "get_redis",
        lambda: type("Redis", (), {"exists": lambda _self, _key: 1})(),
    )

    response = TestClient(app).get("/ready")
    assert response.status_code == 200


def test_readiness_fails_closed_when_required_redis_is_unavailable(monkeypatch):
    from app.api import health as health_api
    from app.core import redis_client
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
    monkeypatch.setattr(settings, "process_role", "api")
    monkeypatch.setattr(settings, "redis_required", True)
    monkeypatch.setattr(redis_client, "ping", lambda: (False, "ConnectionError"))
    monkeypatch.setattr(redis_client, "enabled", lambda: False)

    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert "redis_unavailable" in response.json()["data"]["reasons"]
