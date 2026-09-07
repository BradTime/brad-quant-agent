"""Role-aware API and background-worker lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field

from app.core import redis_client
from app.core.config import settings

logger = logging.getLogger(__name__)


def worker_instance_id() -> str:
    return os.environ.get("HOSTNAME") or os.uname().nodename


class WorkerHeartbeat:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _publish(self) -> None:
        client = redis_client.get_redis()
        if client is None:
            return
        from app.services.backtest_jobs import job_worker_running

        scheduling_enabled = (
            settings.enable_scheduler or settings.enable_auth_outbox_scheduler
        )
        if scheduling_enabled:
            from app.services.scheduler_leader import scheduler_leader_running

            components_healthy = scheduler_leader_running()
        else:
            components_healthy = True
        instance_key = redis_client.key(
            "health", "worker", worker_instance_id()
        )
        if not job_worker_running() or not components_healthy:
            client.delete(instance_key)
            return
        ttl = max(settings.worker_heartbeat_ttl_seconds, 5)
        timestamp = str(int(time.time() * 1000))
        client.set(
            redis_client.key("health", "worker", "any"),
            timestamp,
            ex=ttl,
        )
        client.set(instance_key, timestamp, ex=ttl)

    def _run(self) -> None:
        interval = max(settings.worker_heartbeat_ttl_seconds / 3, 1)
        while not self._stop.is_set():
            try:
                self._publish()
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker heartbeat failed: %s", type(exc).__name__)
            self._stop.wait(interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="worker-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


@dataclass
class RuntimeState:
    tasks: list[asyncio.Task] = field(default_factory=list)
    scheduler_started: bool = False
    scheduler_leader_started: bool = False
    job_worker_started: bool = False
    heartbeat: WorkerHeartbeat | None = None


async def start_api_runtime() -> RuntimeState:
    state = RuntimeState()
    from app.ws.broadcaster import push_loop

    state.tasks.append(asyncio.create_task(push_loop(), name="quote-ws-broadcaster"))
    if redis_client.enabled():
        from app.ws.redis_bridge import listen_private_events

        state.tasks.append(
            asyncio.create_task(listen_private_events(), name="private-ws-redis-bridge")
        )
    return state


async def stop_api_runtime(state: RuntimeState) -> None:
    for task in state.tasks:
        task.cancel()
    if state.tasks:
        await asyncio.gather(*state.tasks, return_exceptions=True)


def start_worker_runtime() -> RuntimeState:
    state = RuntimeState()
    scheduling_enabled = settings.enable_scheduler or settings.enable_auth_outbox_scheduler
    if scheduling_enabled:
        if redis_client.enabled():
            from app.services.scheduler_leader import start_scheduler_leader

            state.scheduler_leader_started = start_scheduler_leader() is not None
        else:
            from app.services.scheduler import start_scheduler

            start_scheduler()
            state.scheduler_started = True

    from app.services.backtest_jobs import start_job_worker

    start_job_worker()
    state.job_worker_started = True

    if settings.rag_enabled and settings.embedding_warm_on_start:
        from app.ai import embeddings

        embeddings.warm_in_background()

    if redis_client.enabled():
        state.heartbeat = WorkerHeartbeat()
        state.heartbeat.start()
    return state


def stop_worker_runtime(state: RuntimeState) -> None:
    if state.heartbeat is not None:
        state.heartbeat.stop()
    if state.job_worker_started:
        from app.services.backtest_jobs import shutdown_job_worker

        shutdown_job_worker()
    if state.scheduler_leader_started:
        from app.services.scheduler_leader import shutdown_scheduler_leader

        shutdown_scheduler_leader()
    if state.scheduler_started:
        from app.services.scheduler import shutdown_scheduler

        shutdown_scheduler()


async def close_shared_state() -> None:
    await redis_client.close_async_client()
    redis_client.close_sync_client()
