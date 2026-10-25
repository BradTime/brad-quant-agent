"""回测异步任务：入队、认领、取消、worker 消费（H21/H22）。

网格等长任务写入 ``backtest_jobs``；API 进程可同步跑小网格，也可只入队；
``PROCESS_ROLE=worker|all`` 时轮询认领（``FOR UPDATE SKIP LOCKED``）。
不依赖 Redis。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.job import BacktestJob, BacktestJobStatus
from app.schemas.backtest import FullABacktestRequest, GridSearchRequest
from app.services import backtest_run

logger = logging.getLogger(__name__)

_CancelCheck = Callable[[], bool]
_ProgressCb = Callable[[int, int], None]

_worker_stop = threading.Event()
_worker_thread: threading.Thread | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _job_to_dict(row: BacktestJob, *, with_result: bool = True) -> dict[str, Any]:
    request: dict = {}
    result: dict | None = None
    try:
        raw_req = load_envelope(row.request_json, expect="dict", field="request_json")
        request = raw_req if isinstance(raw_req, dict) else {}
    except Exception:  # noqa: BLE001
        request = {}
    if with_result and row.result_json is not None:
        try:
            raw = load_envelope(row.result_json, expect="dict", field="result_json")
            result = raw if isinstance(raw, dict) else {"payload": raw}
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"result corrupt: {exc}"}
    return {
        "id": row.id,
        "userId": row.user_id,
        "kind": row.kind,
        "status": row.status,
        "cancelRequested": bool(row.cancel_requested),
        "progressDone": int(row.progress_done or 0),
        "progressTotal": int(row.progress_total or 0),
        "error": row.error,
        "request": request,
        "result": result,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
    }


def enqueue_grid(user_id: str, req: GridSearchRequest) -> dict[str, Any]:
    """校验网格后入队，立即返回 job 摘要。"""
    config, param_grid, sort_by = backtest_run.config_from_grid_request(req)
    # 预校验（非法参数 / 超限在入队前失败）
    backtest_run._validated_grid_request(config, param_grid, sort_by)  # noqa: SLF001

    keys = [k for k in param_grid if param_grid[k]]

    total = 1
    for k in keys:
        total *= len(param_grid[k])
    if not keys:
        total = 0

    job_id = uuid4().hex
    payload = req.model_dump(mode="json")
    with SessionLocal() as session:
        row = BacktestJob(
            id=job_id,
            user_id=user_id,
            kind="grid",
            status=BacktestJobStatus.QUEUED,
            request_json=dump_envelope(payload),
            progress_done=0,
            progress_total=total,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _job_to_dict(row, with_result=False)


def enqueue_full_a(
    user_id: str, req: FullABacktestRequest
) -> dict[str, Any]:
    from app.backtest.universe import expected_session_dates

    validated = FullABacktestRequest.model_validate(req, from_attributes=True)
    total = len(expected_session_dates(validated.start, validated.end))
    job_id = uuid4().hex
    with SessionLocal() as session:
        existing = session.execute(
            select(BacktestJob.id).where(
                BacktestJob.user_id == user_id,
                BacktestJob.kind == "full_a",
                BacktestJob.status.in_(
                    (BacktestJobStatus.QUEUED, BacktestJobStatus.RUNNING)
                ),
            )
        ).first()
        if existing is not None:
            raise ValueError("已有全 A 回测任务正在排队或运行")
        row = BacktestJob(
            id=job_id,
            user_id=user_id,
            kind="full_a",
            status=BacktestJobStatus.QUEUED,
            request_json=dump_envelope(validated.model_dump(mode="json")),
            progress_done=0,
            progress_total=total,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("已有全 A 回测任务正在排队或运行") from exc
        session.refresh(row)
        return _job_to_dict(row, with_result=False)


def get_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.get(BacktestJob, job_id)
        if row is None or row.user_id != user_id:
            return None
        return _job_to_dict(row)


def request_cancel(user_id: str, job_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.execute(
            select(BacktestJob)
            .where(
                BacktestJob.id == job_id,
                BacktestJob.user_id == user_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.status in {
            BacktestJobStatus.COMPLETED,
            BacktestJobStatus.FAILED,
            BacktestJobStatus.CANCELLED,
        }:
            return _job_to_dict(row)
        row.cancel_requested = True
        if row.status == BacktestJobStatus.QUEUED:
            row.status = BacktestJobStatus.CANCELLED
            row.finished_at = _now()
            row.error = "cancelled"
        session.commit()
        session.refresh(row)
        return _job_to_dict(row)


def _is_cancel_requested(job_id: str, claim_token: str) -> bool:
    with SessionLocal() as session:
        row = session.get(BacktestJob, job_id)
        return bool(
            row is None
            or row.cancel_requested
            or row.claim_token != claim_token
        )


def _set_progress(
    job_id: str,
    claim_token: str,
    done: int,
    total: int,
) -> None:
    with SessionLocal() as session:
        row = session.execute(
            select(BacktestJob)
            .where(
                BacktestJob.id == job_id,
                BacktestJob.claim_token == claim_token,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return
        row.progress_done = done
        row.progress_total = total
        row.updated_at = _now()
        session.commit()


def _finish(
    job_id: str,
    claim_token: str,
    *,
    status: BacktestJobStatus | str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    with SessionLocal() as session:
        row = session.execute(
            select(BacktestJob)
            .where(
                BacktestJob.id == job_id,
                BacktestJob.claim_token == claim_token,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return
        if row.cancel_requested:
            status = BacktestJobStatus.CANCELLED
            error = "cancelled"
        row.status = str(status)
        row.finished_at = _now()
        row.updated_at = _now()
        if result is not None:
            row.result_json = dump_envelope(result)
        if error:
            row.error = error[:512]
        session.commit()


def claim_next_job() -> BacktestJob | None:
    """认领一条 queued 任务（Postgres SKIP LOCKED；SQLite 降级普通锁）。"""
    with SessionLocal() as session:
        stale_before = _now() - timedelta(
            seconds=settings.backtest_job_lease_seconds
        )
        stmt = (
            select(BacktestJob)
            .where(
                or_(
                    BacktestJob.status == BacktestJobStatus.QUEUED,
                    (
                        (BacktestJob.status == BacktestJobStatus.RUNNING)
                        & (BacktestJob.updated_at < stale_before)
                    ),
                )
            )
            .order_by(BacktestJob.created_at.asc())
            .limit(1)
        )
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        else:
            stmt = stmt.with_for_update()
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        if row.cancel_requested:
            row.status = BacktestJobStatus.CANCELLED
            row.finished_at = _now()
            row.error = "cancelled"
            session.commit()
            return None
        row.status = BacktestJobStatus.RUNNING
        row.claim_token = uuid4().hex
        row.started_at = _now()
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        # detach values needed outside session
        session.expunge(row)
        return row


def process_job(row: BacktestJob) -> None:
    """Execute a claimed grid-search or chunked full-A job."""
    job_id = row.id
    claim_token = row.claim_token
    if not claim_token:
        _finish(
            job_id,
            "",
            status=BacktestJobStatus.FAILED,
            error="missing claim token",
        )
        return
    try:
        raw = load_envelope(row.request_json, expect="dict", field="request_json")
        if not isinstance(raw, dict):
            _finish(
                job_id,
                claim_token,
                status=BacktestJobStatus.FAILED,
                error="invalid request payload",
            )
            return
        def cancel_check() -> bool:
            return _is_cancel_requested(job_id, claim_token)

        def on_progress(done: int, total: int) -> None:
            _set_progress(job_id, claim_token, done, total)

        if row.kind == "full_a":
            req = FullABacktestRequest.model_validate(raw)
            result = backtest_run.run_full_a_and_save(
                row.user_id,
                req,
                cancel_check=cancel_check,
                on_progress=on_progress,
                job_id=job_id,
                claim_token=claim_token,
            )
            if result.get("cancelled"):
                _finish(
                    job_id,
                    claim_token,
                    status=BacktestJobStatus.CANCELLED,
                    result=result,
                    error="cancelled",
                )
                return
            if result.pop("_jobFinalized", False):
                return
            if result.get("error"):
                _finish(
                    job_id,
                    claim_token,
                    status=BacktestJobStatus.FAILED,
                    result=result,
                    error=str(result["error"])[:512],
                )
                return
            _finish(
                job_id,
                claim_token,
                status=BacktestJobStatus.COMPLETED,
                result=result,
            )
            return
        if row.kind != "grid":
            _finish(
                job_id,
                claim_token,
                status=BacktestJobStatus.FAILED,
                error=f"unsupported job kind: {row.kind}",
            )
            return
        req = GridSearchRequest.model_validate(raw)
        config, param_grid, sort_by = backtest_run.config_from_grid_request(req)

        result = backtest_run.grid_search(
            config,
            param_grid,
            sort_by,
            cancel_check=cancel_check,
            on_progress=on_progress,
        )
        if result.get("cancelled"):
            _finish(
                job_id,
                claim_token,
                status=BacktestJobStatus.CANCELLED,
                result=result,
                error="cancelled",
            )
            return
        if result.get("error") and not result.get("results"):
            _finish(
                job_id,
                claim_token,
                status=BacktestJobStatus.FAILED,
                result=result,
                error=str(result["error"])[:512],
            )
            return
        _finish(
            job_id,
            claim_token,
            status=BacktestJobStatus.COMPLETED,
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("backtest job %s failed", job_id)
        _finish(
            job_id,
            claim_token,
            status=BacktestJobStatus.FAILED,
            error=str(exc)[:512],
        )


def worker_loop_once() -> bool:
    """认领并处理至多一条任务。返回是否处理过。"""
    row = claim_next_job()
    if row is None:
        return False
    process_job(row)
    return True


def _worker_main() -> None:
    interval = max(0.5, float(settings.backtest_job_poll_seconds))
    logger.info("backtest job worker started (poll=%.1fs)", interval)
    while not _worker_stop.is_set():
        try:
            worked = worker_loop_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("job worker tick failed: %s", type(exc).__name__)
            worked = False
        if not worked:
            _worker_stop.wait(interval)


def start_job_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_stop.clear()
    _worker_thread = threading.Thread(
        target=_worker_main, name="backtest-job-worker", daemon=True
    )
    _worker_thread.start()


def shutdown_job_worker() -> None:
    _worker_stop.set()
    thread = _worker_thread
    if thread and thread.is_alive():
        thread.join(timeout=5)


def job_worker_running() -> bool:
    return bool(_worker_thread and _worker_thread.is_alive())
