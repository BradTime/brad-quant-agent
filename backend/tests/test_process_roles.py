"""Role lifecycle and split-process configuration."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_split_roles_require_redis():
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(process_role="api", redis_url="")
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(process_role="worker", redis_url="")


def test_api_runtime_starts_only_api_tasks(monkeypatch: pytest.MonkeyPatch):
    from app import runtime
    from app.ws import broadcaster

    started = asyncio.Event()

    async def push_loop():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(broadcaster, "push_loop", push_loop)
    monkeypatch.setattr(runtime.redis_client, "enabled", lambda: False)

    async def run():
        state = await runtime.start_api_runtime()
        await asyncio.wait_for(started.wait(), timeout=1)
        assert len(state.tasks) == 1
        assert state.job_worker_started is False
        assert state.scheduler_started is False
        await runtime.stop_api_runtime(state)

    asyncio.run(run())


def test_worker_runtime_starts_only_worker_components(
    monkeypatch: pytest.MonkeyPatch,
):
    from app import runtime
    from app.services import backtest_jobs, scheduler

    events: list[str] = []
    monkeypatch.setattr(runtime.redis_client, "enabled", lambda: False)
    monkeypatch.setattr(runtime.settings, "enable_scheduler", True)
    monkeypatch.setattr(runtime.settings, "enable_auth_outbox_scheduler", False)
    monkeypatch.setattr(runtime.settings, "rag_enabled", False)
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: events.append("scheduler-start"))
    monkeypatch.setattr(scheduler, "shutdown_scheduler", lambda: events.append("scheduler-stop"))
    monkeypatch.setattr(backtest_jobs, "start_job_worker", lambda: events.append("jobs-start"))
    monkeypatch.setattr(backtest_jobs, "shutdown_job_worker", lambda: events.append("jobs-stop"))

    state = runtime.start_worker_runtime()
    runtime.stop_worker_runtime(state)

    assert events == ["scheduler-start", "jobs-start", "jobs-stop", "scheduler-stop"]


def test_worker_heartbeat_is_instance_specific_and_component_aware(
    monkeypatch: pytest.MonkeyPatch,
):
    from app import runtime
    from app.services import backtest_jobs

    class FakeRedis:
        def __init__(self):
            self.values: dict[str, str] = {}

        def set(self, key, value, ex):
            self.values[key] = value

        def delete(self, key):
            self.values.pop(key, None)

    fake = FakeRedis()
    healthy = True
    monkeypatch.setattr(runtime.redis_client, "get_redis", lambda: fake)
    monkeypatch.setattr(runtime.settings, "enable_scheduler", False)
    monkeypatch.setattr(runtime.settings, "enable_auth_outbox_scheduler", False)
    monkeypatch.setattr(runtime, "worker_instance_id", lambda: "worker-a")
    monkeypatch.setattr(backtest_jobs, "job_worker_running", lambda: healthy)

    heartbeat = runtime.WorkerHeartbeat()
    heartbeat._publish()
    instance_key = runtime.redis_client.key("health", "worker", "worker-a")
    assert instance_key in fake.values

    healthy = False
    heartbeat._publish()
    assert instance_key not in fake.values
