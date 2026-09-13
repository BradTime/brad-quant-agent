"""Lease-protected scheduled training/inference operations."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.backtest.data import _ingestion_run_quality_in_session
from app.backtest.universe import expected_session_dates
from app.core.config import settings
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.evolution import EvolutionProgram
from app.models.market import AdjustFactor, DailyBar
from app.models.prediction import PredictionForecast, PredictionModelRun
from app.models.prediction_ops import PredictionOpsJob
from app.models.universe import UniverseMembershipDaily, UniverseSnapshotDaily
from app.providers.symbols import normalize_a_share_codes
from app.services import (
    prediction_registry,
    prediction_training,
    universe_membership,
)

MAX_ATTEMPTS = 3
OPS_IMPLEMENTATION_VERSION = "ops-v3-pit-v4"
_LOCAL_EXECUTION_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_EXECUTION_LOCKS_GUARD = threading.Lock()
_COMPLETENESS_CACHE_LOCK = threading.Lock()
_COMPLETENESS_CACHE: tuple[
    tuple[str, tuple[str, ...], int],
    float,
    dict[str, Any],
] | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _advisory_key(job_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(job_id.encode()).digest()[:8],
        "big",
        signed=True,
    )


@contextmanager
def _execution_lock(job_id: str) -> Iterator[bool]:
    with SessionLocal() as session:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            connection = session.connection()
            acquired = bool(
                connection.scalar(
                    select(
                        func.pg_try_advisory_lock(
                            _advisory_key(job_id)
                        )
                    )
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(
                        select(
                            func.pg_advisory_unlock(
                                _advisory_key(job_id)
                            )
                        )
                    )
            return
    with _LOCAL_EXECUTION_LOCKS_GUARD:
        lock = _LOCAL_EXECUTION_LOCKS.setdefault(
            job_id, threading.Lock()
        )
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def configured_codes() -> list[str]:
    raw = [
        value.strip()
        for value in settings.prediction_ops_codes.split(",")
        if value.strip()
    ]
    return normalize_a_share_codes(raw) if raw else []


def _idempotency_key(
    job_type: str,
    scheduled_for: date,
    provider: str,
    codes: list[str],
    rolling_years: int,
) -> str:
    code_hash = hashlib.sha256(
        ",".join(sorted(codes)).encode()
    ).hexdigest()[:16]
    return (
        f"{job_type}:{scheduled_for.isoformat()}:{provider}:"
        f"{rolling_years}y:{OPS_IMPLEMENTATION_VERSION}:{code_hash}"
    )


def enqueue(
    *,
    job_type: str,
    scheduled_for: date,
    codes: list[str],
    provider: str,
    requested_by_user_id: str | None,
) -> dict[str, Any]:
    if job_type not in {"weekly_train", "daily_infer"}:
        raise ValueError("预测运营任务类型无效")
    codes = normalize_a_share_codes(codes)
    if not 1 <= len(codes) <= 20 or len(set(codes)) != len(codes):
        raise ValueError("预测运营代码必须为 1–20 个不重复 A 股代码")
    if provider not in {"lightgbm", "xgboost"}:
        raise ValueError("预测模型 provider 无效")
    key = _idempotency_key(
        job_type,
        scheduled_for,
        provider,
        codes,
        settings.prediction_rolling_years,
    )
    job_id = str(uuid4())
    now = _now()
    payload = {
        "jobType": job_type,
        "scheduledFor": scheduled_for.isoformat(),
        "codes": sorted(codes),
        "provider": provider,
        "rollingYears": settings.prediction_rolling_years,
        "implementationVersion": OPS_IMPLEMENTATION_VERSION,
    }
    try:
        with SessionLocal.begin() as session:
            session.add(
                PredictionOpsJob(
                    id=job_id,
                    requested_by_user_id=requested_by_user_id,
                    requested_by_user_id_snapshot=(
                        requested_by_user_id or "system"
                    ),
                    job_type=job_type,
                    scheduled_for=scheduled_for,
                    idempotency_key=key,
                    status="queued",
                    payload_json=dump_envelope(payload),
                    attempts=0,
                    next_attempt_at=now,
                )
            )
            session.flush()
    except IntegrityError:
        with SessionLocal() as session:
            existing = session.execute(
                select(PredictionOpsJob).where(
                    PredictionOpsJob.idempotency_key == key
                )
            ).scalar_one()
            return _serialize(existing)
    with SessionLocal() as session:
        return _serialize(session.get(PredictionOpsJob, job_id))


def enqueue_scheduled_training() -> dict[str, Any] | None:
    if not settings.prediction_ops_enabled:
        return None
    codes = configured_codes()
    if not codes:
        raise ValueError("自动训练已启用但 PREDICTION_OPS_CODES 为空")
    latest = _latest_snapshot_date()
    if latest is None:
        raise ValueError("没有可用于训练的 PIT 股票池快照")
    completeness = data_completeness()
    if not completeness["ready"]:
        raise ValueError("3–5 年 PIT 训练数据完整率门禁未通过")
    return enqueue(
        job_type="weekly_train",
        scheduled_for=latest,
        codes=codes,
        provider=settings.prediction_ops_provider,
        requested_by_user_id=None,
    )


def enqueue_scheduled_inference() -> dict[str, Any] | None:
    if not settings.prediction_ops_enabled:
        return None
    codes = configured_codes()
    if not codes:
        raise ValueError("自动推理已启用但 PREDICTION_OPS_CODES 为空")
    latest = _latest_snapshot_date()
    if latest is None:
        raise ValueError("没有可用于推理的 PIT 股票池快照")
    return enqueue(
        job_type="daily_infer",
        scheduled_for=latest,
        codes=codes,
        provider=settings.prediction_ops_provider,
        requested_by_user_id=None,
    )


def _latest_snapshot_date() -> date | None:
    with SessionLocal() as session:
        return session.scalar(
            select(func.max(UniverseSnapshotDaily.trade_date)).where(
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION
            )
        )


def _serialize(row: PredictionOpsJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "jobType": row.job_type,
        "scheduledFor": row.scheduled_for.isoformat(),
        "status": row.status,
        "attempts": row.attempts,
        "payload": load_envelope(row.payload_json, expect="dict"),
        "result": (
            load_envelope(row.result_json, expect="dict")
            if row.result_json is not None
            else None
        ),
        "errorCode": row.error_code,
        "createdAt": row.created_at.isoformat(),
        "startedAt": (
            row.started_at.isoformat() if row.started_at else None
        ),
        "completedAt": (
            row.completed_at.isoformat() if row.completed_at else None
        ),
    }


def _claim() -> tuple[str, str] | None:
    now = _now()
    token = str(uuid4())
    with SessionLocal.begin() as session:
        statement = (
            select(PredictionOpsJob)
            .where(
                PredictionOpsJob.attempts < MAX_ATTEMPTS,
                PredictionOpsJob.next_attempt_at <= now,
                or_(
                    PredictionOpsJob.status == "queued",
                    (
                        (PredictionOpsJob.status == "running")
                        & (
                            PredictionOpsJob.lease_expires_at
                            <= now
                        )
                    ),
                ),
            )
            .order_by(PredictionOpsJob.created_at)
            .limit(1)
        )
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        else:
            statement = statement.with_for_update()
        row = session.execute(statement).scalar_one_or_none()
        if row is None:
            return None
        if (
            row.status == "running"
            and session.get_bind().dialect.name == "postgresql"
        ):
            available = session.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        _advisory_key(row.id)
                    )
                )
            )
            if not available:
                return None
        row.status = "running"
        row.claim_token = token
        row.lease_expires_at = now + timedelta(
            seconds=settings.prediction_ops_job_lease_seconds
        )
        row.started_at = row.started_at or now
        row.attempts += 1
        return row.id, token


def _renew(job_id: str, token: str) -> bool:
    with SessionLocal.begin() as session:
        row = session.execute(
            select(PredictionOpsJob)
            .where(
                PredictionOpsJob.id == job_id,
                PredictionOpsJob.claim_token == token,
                PredictionOpsJob.status == "running",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return False
        row.lease_expires_at = _now() + timedelta(
            seconds=settings.prediction_ops_job_lease_seconds
        )
        return True


@contextmanager
def _heartbeat(job_id: str, token: str) -> Iterator[None]:
    stop = threading.Event()
    interval = max(
        30, settings.prediction_ops_job_lease_seconds // 3
    )

    def renew() -> None:
        while not stop.wait(interval):
            if not _renew(job_id, token):
                return

    thread = threading.Thread(
        target=renew,
        name=f"prediction-ops-lease-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


def _existing_training_result(version: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.execute(
            select(PredictionModelRun).where(
                PredictionModelRun.version == version
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.status == "failed":
            return None
        if row.status == "registering":
            recovered = prediction_registry.recover_registration(version)
            return recovered if recovered["status"] != "failed" else None
        return {
            "id": row.id,
            "version": row.version,
            "status": row.status,
            "artifactSha256": row.artifact_sha256,
        }


def _job_guard(job_id: str, token: str):
    def guard(session) -> bool:
        return (
            session.execute(
                select(PredictionOpsJob.id)
                .where(
                    PredictionOpsJob.id == job_id,
                    PredictionOpsJob.claim_token == token,
                    PredictionOpsJob.status == "running",
                    PredictionOpsJob.lease_expires_at > _now(),
                )
                .with_for_update()
            ).scalar_one_or_none()
            is not None
        )

    return guard


def _execute(
    row: PredictionOpsJob,
    *,
    claim_token: str,
) -> dict[str, Any]:
    payload = load_envelope(row.payload_json, expect="dict")
    latest = _latest_snapshot_date()
    if latest is None or (
        row.job_type == "daily_infer" and latest != row.scheduled_for
    ) or (
        row.job_type == "weekly_train" and latest < row.scheduled_for
    ):
        raise ValueError("任务日期没有对应的可信 PIT 物化状态")
    codes = payload["codes"]
    if row.job_type == "daily_infer":
        with SessionLocal() as session:
            champion = prediction_registry._champion(session)
            existing_codes = set(
                session.execute(
                    select(PredictionForecast.code).where(
                        PredictionForecast.model_run_id
                        == champion.id,
                        PredictionForecast.signal_date
                        == row.scheduled_for,
                        PredictionForecast.code.in_(codes),
                    )
                ).scalars()
            )
        missing_codes = [
            code for code in codes if code not in existing_codes
        ]
        forecasts = []
        if missing_codes:
            features = (
                prediction_training.build_inference_features_from_database(
                    signal_date=row.scheduled_for,
                    codes=missing_codes,
                )
            )
            job_guard = _job_guard(row.id, claim_token)

            def inference_guard(session) -> bool:
                pinned = session.get(
                    PredictionModelRun,
                    champion.id,
                    with_for_update=True,
                )
                return bool(
                    job_guard(session)
                    and pinned is not None
                    and pinned.is_champion
                )

            forecasts = prediction_registry.infer_model_and_store(
                champion.id,
                features,
                publication_guard=inference_guard,
            )
        return {
            "forecastCount": len(existing_codes) + len(forecasts),
            "modelRunIds": [champion.id],
        }
    provider = payload["provider"]
    version_base = (
        f"weekly-{row.scheduled_for.isoformat()}-{provider}-"
        f"{payload['rollingYears']}y-v3-"
        f"{hashlib.sha256(','.join(codes).encode()).hexdigest()[:8]}"
    )
    for attempt in range(1, row.attempts + 1):
        existing = _existing_training_result(
            f"{version_base}-a{attempt}"
        )
        if existing is not None:
            return existing
    version = f"{version_base}-a{row.attempts}"
    start = row.scheduled_for - timedelta(
        days=365 * int(payload["rollingYears"])
    )
    return prediction_training.train_from_database(
        version=version,
        provider=provider,
        codes=codes,
        start=start,
        end=row.scheduled_for,
        user_id=row.requested_by_user_id,
        publication_guard=_job_guard(row.id, claim_token),
    )


def _finish(
    job_id: str,
    token: str,
    *,
    result: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> bool:
    now = _now()
    with SessionLocal.begin() as session:
        row = session.execute(
            select(PredictionOpsJob)
            .where(
                PredictionOpsJob.id == job_id,
                PredictionOpsJob.claim_token == token,
                PredictionOpsJob.status == "running",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return False
        row.claim_token = None
        row.lease_expires_at = None
        if error is None:
            row.status = "completed"
            row.result_json = dump_envelope(result or {})
            row.error_code = None
            row.completed_at = now
        elif row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            row.error_code = type(error).__name__[:64]
            row.completed_at = now
        else:
            row.status = "queued"
            row.error_code = type(error).__name__[:64]
            row.next_attempt_at = now + timedelta(
                minutes=5 * (2 ** (row.attempts - 1))
            )
        return True


def process_next() -> bool:
    claimed = _claim()
    if claimed is None:
        return False
    job_id, token = claimed
    try:
        with _execution_lock(job_id) as acquired:
            if not acquired:
                return False
            with SessionLocal() as session:
                row = session.get(PredictionOpsJob, job_id)
                with _heartbeat(job_id, token):
                    result = _execute(row, claim_token=token)
    except Exception as exc:  # noqa: BLE001
        _finish(job_id, token, error=exc)
        return False
    return _finish(job_id, token, result=result)


def list_jobs(*, limit: int = 100) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(PredictionOpsJob)
            .order_by(PredictionOpsJob.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_serialize(row) for row in rows]


def data_completeness() -> dict[str, Any]:
    global _COMPLETENESS_CACHE
    codes = configured_codes()
    latest = _latest_snapshot_date()
    if latest is None:
        return {"latestDate": None, "codes": codes, "ready": False}
    cache_key = (
        latest.isoformat(),
        tuple(codes),
        settings.prediction_rolling_years,
    )
    with _COMPLETENESS_CACHE_LOCK:
        cached = _COMPLETENESS_CACHE
        if (
            cached is not None
            and cached[0] == cache_key
            and cached[1] > time.monotonic()
        ):
            return dict(cached[2])
    training_start = latest - timedelta(
        days=365 * settings.prediction_rolling_years
    )
    # Regime needs 120 days and benchmark loader itself requests 14 more.
    start = training_start - timedelta(days=134)
    sessions = [
        (
            date.fromisoformat(value)
            if isinstance(value, str)
            else value
        )
        for value in expected_session_dates(start, latest)
    ]
    with SessionLocal() as session:
        snapshot_count = session.scalar(
            select(func.count(UniverseSnapshotDaily.trade_date)).where(
                UniverseSnapshotDaily.trade_date.in_(sessions),
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION,
            )
        )
        membership_count = (
            session.scalar(
                select(func.count()).select_from(
                    UniverseMembershipDaily
                ).where(
                    UniverseMembershipDaily.trade_date.in_(sessions),
                    UniverseMembershipDaily.code.in_(codes),
                    UniverseMembershipDaily.rules_version
                    == universe_membership.RULES_VERSION,
                )
            )
            if codes
            else 0
        )
        eligible_cells = (
            session.scalar(
                select(func.count()).select_from(
                    UniverseMembershipDaily
                ).where(
                    UniverseMembershipDaily.trade_date.in_(sessions),
                    UniverseMembershipDaily.code.in_(codes),
                    UniverseMembershipDaily.rules_version
                    == universe_membership.RULES_VERSION,
                    UniverseMembershipDaily.eligible.is_(True),
                )
            )
            if codes
            else 0
        )
        eligible_by_code = (
            dict(
                session.execute(
                    select(
                        UniverseMembershipDaily.code,
                        func.count(),
                    )
                    .where(
                        UniverseMembershipDaily.trade_date.in_(
                            sessions
                        ),
                        UniverseMembershipDaily.code.in_(codes),
                        UniverseMembershipDaily.rules_version
                        == universe_membership.RULES_VERSION,
                        UniverseMembershipDaily.eligible.is_(True),
                    )
                    .group_by(UniverseMembershipDaily.code)
                ).all()
            )
            if codes
            else {}
        )
        bar_count = (
            session.scalar(
                select(func.count())
                .select_from(UniverseMembershipDaily)
                .join(
                    DailyBar,
                    (
                        DailyBar.code
                        == UniverseMembershipDaily.code
                    )
                    & (
                        DailyBar.trade_date
                        == UniverseMembershipDaily.trade_date
                    ),
                )
                .where(
                    UniverseMembershipDaily.trade_date.in_(sessions),
                    UniverseMembershipDaily.code.in_(codes),
                    UniverseMembershipDaily.rules_version
                    == universe_membership.RULES_VERSION,
                    UniverseMembershipDaily.eligible.is_(True),
                    DailyBar.open.is_not(None),
                    DailyBar.high.is_not(None),
                    DailyBar.low.is_not(None),
                    DailyBar.close.is_not(None),
                    DailyBar.volume.is_not(None),
                    DailyBar.amount.is_not(None),
                    DailyBar.open > 0,
                    DailyBar.high > 0,
                    DailyBar.low > 0,
                    DailyBar.close > 0,
                    DailyBar.low <= DailyBar.open,
                    DailyBar.low <= DailyBar.close,
                    DailyBar.high >= DailyBar.open,
                    DailyBar.high >= DailyBar.close,
                    DailyBar.volume >= 0,
                    DailyBar.amount >= 0,
                )
            )
            if codes
            else 0
        )
        factor_codes = (
            session.scalar(
                select(func.count(func.distinct(AdjustFactor.code))).where(
                    AdjustFactor.code.in_(codes),
                    AdjustFactor.ex_date <= latest,
                    AdjustFactor.back_adjust_factor.is_not(None),
                    AdjustFactor.back_adjust_factor > 0,
                )
            )
            if codes
            else 0
        )
        factor_cells = (
            session.scalar(
                select(func.count())
                .select_from(UniverseMembershipDaily)
                .join(
                    AdjustFactor,
                    (
                        AdjustFactor.code
                        == UniverseMembershipDaily.code
                    )
                    & (
                        AdjustFactor.ex_date
                        == UniverseMembershipDaily.trade_date
                    ),
                )
                .where(
                    UniverseMembershipDaily.trade_date.in_(sessions),
                    UniverseMembershipDaily.code.in_(codes),
                    UniverseMembershipDaily.rules_version
                    == universe_membership.RULES_VERSION,
                    UniverseMembershipDaily.eligible.is_(True),
                    AdjustFactor.back_adjust_factor.is_not(None),
                    AdjustFactor.back_adjust_factor > 0,
                )
            )
            if codes
            else 0
        )
        audited_codes = sum(
            _ingestion_run_quality_in_session(
                session,
                code,
                sessions[0].isoformat(),
                latest.isoformat(),
                "1d",
                actual_start=sessions[0],
                actual_end=latest,
            )
            is None
            for code in codes
        ) if sessions and codes else 0
        benchmark_bar_count = session.scalar(
            select(func.count()).select_from(DailyBar).where(
                DailyBar.trade_date.in_(sessions),
                DailyBar.code == "000300.SH",
                DailyBar.open.is_not(None),
                DailyBar.high.is_not(None),
                DailyBar.low.is_not(None),
                DailyBar.close.is_not(None),
                DailyBar.volume.is_not(None),
                DailyBar.amount.is_not(None),
                DailyBar.open > 0,
                DailyBar.high > 0,
                DailyBar.low > 0,
                DailyBar.close > 0,
                DailyBar.low <= DailyBar.open,
                DailyBar.low <= DailyBar.close,
                DailyBar.high >= DailyBar.open,
                DailyBar.high >= DailyBar.close,
                DailyBar.volume >= 0,
                DailyBar.amount >= 0,
            )
        )
        benchmark_factor = session.scalar(
            select(func.count()).select_from(AdjustFactor).where(
                AdjustFactor.code == "000300.SH",
                AdjustFactor.ex_date <= latest,
                AdjustFactor.back_adjust_factor.is_not(None),
                AdjustFactor.back_adjust_factor > 0,
            )
        )
        benchmark_audit = (
            _ingestion_run_quality_in_session(
                session,
                "000300.SH",
                start.isoformat(),
                latest.isoformat(),
                "1d",
                actual_start=sessions[0],
                actual_end=latest,
            )
            if sessions
            else "untracked"
        )
    expected_cells = len(sessions) * len(codes)
    result = {
        "latestDate": latest.isoformat(),
        "startDate": sessions[0].isoformat() if sessions else None,
        "trainingStartDate": training_start.isoformat(),
        "sessionCount": len(sessions),
        "trainingWindowYears": settings.prediction_rolling_years,
        "codes": codes,
        "snapshotCoverage": (
            snapshot_count / len(sessions) if sessions else 0
        ),
        "membershipCoverage": (
            membership_count / expected_cells
            if expected_cells
            else 0
        ),
        "barCoverage": (
            bar_count / eligible_cells if eligible_cells else 0
        ),
        "eligibleBarCells": eligible_cells,
        "eligibleSessionsByCode": eligible_by_code,
        "minimumEligibleSessionsPerCode": 252,
        "adjustFactorCodeCoverage": (
            factor_codes / len(codes) if codes else 0
        ),
        "adjustFactorCoverage": (
            min(1.0, factor_cells / eligible_cells)
            if eligible_cells
            else 0
        ),
        "auditedIngestionCodeCoverage": (
            audited_codes / len(codes) if codes else 0
        ),
        "benchmarkBarCoverage": (
            benchmark_bar_count / len(sessions) if sessions else 0
        ),
        "benchmarkAdjustmentReady": bool(benchmark_factor),
        "benchmarkIngestionQuality": (
            benchmark_audit or "full"
        ),
        "ready": bool(
            codes
            and snapshot_count == len(sessions)
            and membership_count == expected_cells
            and eligible_cells > 0
            and set(eligible_by_code) == set(codes)
            and min(eligible_by_code.values()) >= 252
            and bar_count == eligible_cells
            and factor_codes == len(codes)
            and factor_cells >= eligible_cells
            and audited_codes == len(codes)
            and benchmark_bar_count == len(sessions)
            and bool(benchmark_factor)
            and benchmark_audit is None
        ),
    }
    with _COMPLETENESS_CACHE_LOCK:
        _COMPLETENESS_CACHE = (
            cache_key,
            time.monotonic() + 300,
            result,
        )
    return dict(result)


def dashboard() -> dict[str, Any]:
    with SessionLocal() as session:
        models = session.execute(
            select(PredictionModelRun)
            .order_by(PredictionModelRun.created_at.desc())
            .limit(20)
        ).scalars().all()
        programs = session.execute(
            select(EvolutionProgram)
            .order_by(EvolutionProgram.created_at.desc())
            .limit(20)
        ).scalars().all()
    return {
        "automationEnabled": settings.prediction_ops_enabled,
        "provider": settings.prediction_ops_provider,
        "models": [
            {
                "id": row.id,
                "version": row.version,
                "provider": row.provider,
                "status": row.status,
                "isChampion": row.is_champion,
                "trainingStart": row.training_start.isoformat(),
                "trainingEnd": row.training_end.isoformat(),
                "metrics": load_envelope(
                    row.metrics_json, expect="dict"
                ),
                "createdAt": row.created_at.isoformat(),
            }
            for row in models
        ],
        "programs": [
            {
                "id": row.id,
                "modelRunId": row.model_run_id,
                "stage": row.stage,
                "simulationSessions": row.simulation_sessions,
                "shadowSessions": row.shadow_sessions,
                "metrics": load_envelope(
                    row.metrics_json, expect="dict"
                ),
                "failureReason": row.failure_reason,
            }
            for row in programs
        ],
        "jobs": list_jobs(limit=50),
        "dataCompleteness": data_completeness(),
    }
