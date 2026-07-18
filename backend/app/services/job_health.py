"""Background job health registry for readiness probes."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class JobHealth:
    job_id: str
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_duration_ms: float | None = None
    runs: int = 0


_jobs: dict[str, JobHealth] = {}


def record_success(job_id: str, duration_ms: float | None = None) -> None:
    row = _jobs.setdefault(job_id, JobHealth(job_id=job_id))
    row.last_success_at = time.time()
    row.consecutive_failures = 0
    row.last_error = None
    row.last_duration_ms = duration_ms
    row.runs += 1


def record_failure(job_id: str, error: str, duration_ms: float | None = None) -> None:
    row = _jobs.setdefault(job_id, JobHealth(job_id=job_id))
    row.last_failure_at = time.time()
    row.consecutive_failures += 1
    row.last_error = error[:200]
    row.last_duration_ms = duration_ms
    row.runs += 1
    logger.warning(
        "调度任务失败 job=%s consecutive=%s error=%s",
        job_id,
        row.consecutive_failures,
        row.last_error,
    )


def snapshot() -> dict[str, dict]:
    out: dict[str, dict] = {}
    now = time.time()
    for job_id, row in _jobs.items():
        out[job_id] = {
            "lastSuccessAt": row.last_success_at,
            "lastFailureAt": row.last_failure_at,
            "lastError": row.last_error,
            "consecutiveFailures": row.consecutive_failures,
            "lastDurationMs": row.last_duration_ms,
            "runs": row.runs,
            "successAgeSeconds": (
                None
                if row.last_success_at is None
                else round(now - row.last_success_at, 1)
            ),
        }
    return out


def is_healthy(
    *,
    required_jobs: list[str] | None = None,
    max_consecutive_failures: int = 3,
    max_success_age_seconds: float | None = None,
) -> tuple[bool, list[str]]:
    """返回 (ok, reasons)。未跑过的任务不算失败。"""
    reasons: list[str] = []
    jobs = required_jobs or list(_jobs)
    now = time.time()
    for job_id in jobs:
        row = _jobs.get(job_id)
        if row is None:
            continue
        if row.consecutive_failures >= max_consecutive_failures:
            reasons.append(f"{job_id}:consecutive_failures={row.consecutive_failures}")
        if (
            max_success_age_seconds is not None
            and row.last_success_at is not None
            and (now - row.last_success_at) > max_success_age_seconds
        ):
            reasons.append(f"{job_id}:stale_success")
    return (len(reasons) == 0), reasons


def tracked(job_id: str) -> Callable[[F], F]:
    """装饰器：记录任务成功/失败与耗时。异常仍向上抛出（或由调用方吞掉）。"""

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                record_failure(
                    job_id,
                    type(exc).__name__,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                )
                raise
            record_success(
                job_id,
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def reset_for_tests() -> None:
    _jobs.clear()
