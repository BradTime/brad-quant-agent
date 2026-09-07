"""Redis lease that ensures only one worker owns APScheduler jobs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from uuid import uuid4

from app.core import redis_client
from app.core.config import settings

logger = logging.getLogger(__name__)

_RENEW_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisLease:
    def __init__(
        self,
        client,
        lock_key: str,
        *,
        ttl_seconds: int,
        token: str | None = None,
    ) -> None:
        self.client = client
        self.lock_key = lock_key
        self.ttl_seconds = max(int(ttl_seconds), 10)
        self.token = token or uuid4().hex

    def try_acquire(self) -> bool:
        return bool(
            self.client.set(
                self.lock_key,
                self.token,
                nx=True,
                ex=self.ttl_seconds,
            )
        )

    def renew(self) -> bool:
        script = self.client.register_script(_RENEW_SCRIPT)
        return bool(
            script(
                keys=[self.lock_key],
                args=[self.token, self.ttl_seconds],
                client=self.client,
            )
        )

    def release(self) -> bool:
        script = self.client.register_script(_RELEASE_SCRIPT)
        return bool(
            script(
                keys=[self.lock_key],
                args=[self.token],
                client=self.client,
            )
        )


class SchedulerLeader:
    def __init__(
        self,
        lease: RedisLease,
        *,
        on_acquired: Callable[[], object],
        on_lost: Callable[[], object],
        renew_seconds: float,
    ) -> None:
        self.lease = lease
        self.on_acquired = on_acquired
        self.on_lost = on_lost
        self.renew_seconds = max(float(renew_seconds), 1.0)
        self.is_leader = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def tick(self) -> None:
        with self._lock:
            try:
                if not self.is_leader:
                    if not self.lease.try_acquire():
                        return
                    try:
                        self.on_acquired()
                    except Exception:
                        self.lease.release()
                        raise
                    self.is_leader = True
                    logger.info("scheduler leadership acquired")
                    return
                if self.lease.renew():
                    return
                self.on_lost()
                self.is_leader = False
                logger.warning("scheduler leadership lost")
            except Exception as exc:  # noqa: BLE001
                if self.is_leader:
                    try:
                        self.on_lost()
                    except Exception as stop_exc:  # noqa: BLE001
                        logger.warning(
                            "scheduler shutdown after lease error failed: %s",
                            type(stop_exc).__name__,
                        )
                    self.is_leader = False
                logger.warning("scheduler lease tick failed: %s", type(exc).__name__)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.renew_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="scheduler-leader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(self.renew_seconds * 2, 5))
        with self._lock:
            if self.is_leader:
                try:
                    self.on_lost()
                finally:
                    try:
                        self.lease.release()
                    finally:
                        self.is_leader = False

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


_controller: SchedulerLeader | None = None


def start_scheduler_leader() -> SchedulerLeader | None:
    global _controller
    if _controller is not None and _controller.running():
        return _controller
    client = redis_client.get_redis()
    if client is None:
        return None
    from app.services.scheduler import shutdown_scheduler, start_scheduler

    lease = RedisLease(
        client,
        redis_client.key("leader", "scheduler"),
        ttl_seconds=settings.redis_scheduler_lease_seconds,
    )
    _controller = SchedulerLeader(
        lease,
        on_acquired=start_scheduler,
        on_lost=shutdown_scheduler,
        renew_seconds=min(
            settings.redis_scheduler_renew_seconds,
            max(settings.redis_scheduler_lease_seconds / 3, 1),
        ),
    )
    _controller.start()
    return _controller


def shutdown_scheduler_leader() -> None:
    global _controller
    controller = _controller
    _controller = None
    if controller is not None:
        controller.stop()


def scheduler_leader_running() -> bool:
    return bool(_controller and _controller.running())


def scheduler_is_leader() -> bool:
    return bool(_controller and _controller.is_leader)
