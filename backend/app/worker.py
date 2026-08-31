"""Standalone background-worker entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import threading

from sqlalchemy import text

from app.core import redis_client
from app.core.config import settings
from app.db.session import engine
from app.runtime import (
    close_shared_state,
    start_worker_runtime,
    stop_worker_runtime,
    worker_instance_id,
)

logger = logging.getLogger(__name__)


def check() -> int:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("worker database check failed: %s", type(exc).__name__)
        return 1
    redis_ok, _ = redis_client.ping()
    if not redis_ok:
        return 1
    client = redis_client.get_redis()
    if client is not None:
        if not client.exists(
            redis_client.key("health", "worker", worker_instance_id())
        ):
            return 1
        if (
            settings.enable_scheduler or settings.enable_auth_outbox_scheduler
        ) and not client.exists(redis_client.key("leader", "scheduler")):
            return 1
    return 0


def run() -> int:
    if settings.process_role != "worker":
        raise RuntimeError("python -m app.worker requires PROCESS_ROLE=worker")
    state = start_worker_runtime()
    stopped = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        while not stopped.wait(1):
            pass
    finally:
        stop_worker_runtime(state)
        asyncio.run(close_shared_state())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check() if args.check else run()


if __name__ == "__main__":
    raise SystemExit(main())
