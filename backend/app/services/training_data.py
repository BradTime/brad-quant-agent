"""Consent, feedback, review, and privacy lifecycle for training candidates."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import exists, select, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.models.training import (
    AIGenerationTrace,
    AITrainingFeedback,
    TrainingCandidate,
    TrainingConsent,
    TrainingDataset,
    TrainingDatasetItem,
)
from app.services.training_redaction import (
    assert_redacted,
    redact_payload,
    redact_text,
)

ISSUE_LABELS = {
    "incorrect",
    "unsupported",
    "missing_data",
    "wrong_tool",
    "unsafe_advice",
    "unclear",
    "other",
}
REVIEW_STATUSES = {"approved", "rejected", "deprecated"}
TASK_TYPES = {"tool-routing", "grounded-response", "honesty-compliance"}


class TrainingDataError(ValueError):
    """Invalid ownership, consent, feedback, or review transition."""


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_dataset_lifecycle(db) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtext('training-dataset-publication'))"
            )
        )


def _owned_session(db, user_id: str, session_id: str) -> ChatSession | None:
    return db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    ).scalar_one_or_none()


def _consent_data(row: TrainingConsent | None, session_id: str) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "enabled": bool(row and row.enabled),
        "revision": row.revision if row else 0,
        "policyVersion": (
            row.policy_version if row else settings.training_consent_policy_version
        ),
        "grantedAt": row.granted_at.isoformat() if row and row.granted_at else None,
        "revokedAt": row.revoked_at.isoformat() if row and row.revoked_at else None,
    }


def get_consent(user_id: str, session_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        if _owned_session(db, user_id, session_id) is None:
            raise TrainingDataError("会话不存在")
        row = db.execute(
            select(TrainingConsent).where(
                TrainingConsent.user_id == user_id,
                TrainingConsent.session_id == session_id,
            )
        ).scalar_one_or_none()
        return _consent_data(row, session_id)


def is_consent_enabled(user_id: str, session_id: str | None) -> bool:
    if not session_id:
        return False
    with SessionLocal() as db:
        return bool(
            db.execute(
                select(TrainingConsent.enabled).where(
                    TrainingConsent.user_id == user_id,
                    TrainingConsent.session_id == session_id,
                )
            ).scalar_one_or_none()
        )


def _remove_artifact(path_value: str | None) -> None:
    if not path_value:
        return
    root = Path(settings.training_artifact_dir).resolve()
    target = Path(path_value).resolve()
    if root not in target.parents:
        return
    dataset_dir = target.parent
    if dataset_dir.parent == root:
        shutil.rmtree(dataset_dir, ignore_errors=True)


def set_consent(user_id: str, session_id: str, enabled: bool) -> dict[str, Any]:
    now = _now()
    with SessionLocal.begin() as db:
        _lock_dataset_lifecycle(db)
        if _owned_session(db, user_id, session_id) is None:
            raise TrainingDataError("会话不存在")
        row = db.execute(
            select(TrainingConsent).where(
                TrainingConsent.user_id == user_id,
                TrainingConsent.session_id == session_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = TrainingConsent(
                id=str(uuid4()),
                user_id=user_id,
                session_id=session_id,
                enabled=enabled,
                revision=1,
                policy_version=settings.training_consent_policy_version,
            )
            db.add(row)
        elif (
            row.enabled != enabled
            or row.policy_version != settings.training_consent_policy_version
        ):
            row.revision += 1
        row.enabled = enabled
        row.policy_version = settings.training_consent_policy_version
        row.granted_at = now if enabled else row.granted_at
        row.revoked_at = None if enabled else now
        if not enabled:
            traces = db.execute(
                select(AIGenerationTrace).where(
                    AIGenerationTrace.user_id == user_id,
                    AIGenerationTrace.session_id == session_id,
                )
            ).scalars().all()
            trace_ids = [trace.id for trace in traces]
            if trace_ids:
                feedback_rows = db.execute(
                    select(AITrainingFeedback).where(
                        AITrainingFeedback.trace_id.in_(trace_ids)
                    )
                ).scalars().all()
                for feedback in feedback_rows:
                    feedback.comment = None
                    feedback.issue_labels_json = []
                candidates = db.execute(
                    select(TrainingCandidate).where(
                        TrainingCandidate.trace_id.in_(trace_ids)
                    )
                ).scalars().all()
                candidate_ids = [candidate.id for candidate in candidates]
                if candidate_ids:
                    datasets = db.execute(
                        select(TrainingDataset)
                        .join(
                            TrainingDatasetItem,
                            TrainingDatasetItem.dataset_id == TrainingDataset.id,
                        )
                        .where(TrainingDatasetItem.candidate_id.in_(candidate_ids))
                    ).scalars().all()
                    for dataset in datasets:
                        dataset.status = "deprecated"
                        dataset.deprecated_at = now
                        _remove_artifact(dataset.artifact_path)
                        dataset.artifact_path = None
                    for candidate in candidates:
                        candidate.status = "deprecated"
                        candidate.ideal_answer = None
                        candidate.quality_labels_json = []
                        candidate.review_note = None
                for trace in traces:
                    trace.input_text = ""
                    trace.output_text = ""
                    trace.tool_trace_json = None
                    trace.error_type = "consent_revoked"
        db.flush()
        return _consent_data(row, session_id)


def capture_consent_revision(
    user_id: str,
    session_id: str | None,
    *,
    requested: bool,
    is_new: bool,
) -> int | None:
    if not requested:
        return None
    if is_new:
        return 0
    with SessionLocal() as db:
        row = db.execute(
            select(TrainingConsent).where(
                TrainingConsent.user_id == user_id,
                TrainingConsent.session_id == session_id,
                TrainingConsent.enabled.is_(True),
                TrainingConsent.policy_version
                == settings.training_consent_policy_version,
            )
        ).scalar_one_or_none()
        return row.revision if row else None


def record_completed_turn(
    *,
    user_id: str,
    session_id: str,
    user_message_id: str,
    assistant_message_id: str,
    input_text: str,
    output_text: str,
    tool_trace: list[dict[str, Any]],
    model: str,
    provider: str = "deepseek",
    generation_params: dict[str, Any] | None = None,
    prompt_version: str,
    prompt_hash: str,
    tool_schema_version: str,
    latency_ms: int,
    consent_requested: bool,
    consent_revision: int | None = None,
) -> str | None:
    if not consent_requested or consent_revision is None:
        return None
    redacted_input = redact_text(input_text, user_id=user_id)
    redacted_output = redact_text(output_text, user_id=user_id)
    redacted_tools = redact_payload(tool_trace, user_id=user_id)
    assert_redacted((redacted_input, redacted_output, redacted_tools))
    now = _now()
    expires = now + timedelta(days=max(settings.training_trace_retention_days, 1))
    trace_id = str(uuid4())
    with SessionLocal.begin() as db:
        consent = db.execute(
            select(TrainingConsent).where(
                TrainingConsent.user_id == user_id,
                TrainingConsent.session_id == session_id,
            )
        ).scalar_one_or_none()
        if consent is None:
            if consent_revision != 0:
                return None
            consent = TrainingConsent(
                id=str(uuid4()),
                user_id=user_id,
                session_id=session_id,
                enabled=True,
                revision=1,
                policy_version=settings.training_consent_policy_version,
                granted_at=now,
            )
            db.add(consent)
        elif (
            not consent.enabled
            or consent.revision != consent_revision
            or consent.policy_version != settings.training_consent_policy_version
        ):
            return None
        db.add(
            AIGenerationTrace(
                id=trace_id,
                user_id=user_id,
                session_id=session_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                status="complete",
                source_type="chat",
                input_text=redacted_input,
                output_text=redacted_output,
                tool_trace_json=redacted_tools,
                model=model,
                provider=provider,
                generation_params_json=generation_params,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                tool_schema_version=tool_schema_version,
                latency_ms=latency_ms,
                as_of=now,
                consent_policy_version=consent.policy_version,
                redaction_policy_version=settings.training_redaction_policy_version,
                expires_at=expires,
            )
        )
    return trace_id


def record_failed_turn(
    *,
    user_id: str,
    session_id: str | None,
    input_text: str,
    model: str,
    provider: str = "deepseek",
    generation_params: dict[str, Any] | None = None,
    prompt_version: str,
    prompt_hash: str,
    tool_schema_version: str,
    latency_ms: int,
    error_type: str,
    consent_requested: bool,
    consent_revision: int | None = None,
    status: str = "failed",
) -> str | None:
    if (
        not consent_requested
        or consent_revision is None
        or status not in {"failed", "interrupted"}
    ):
        return None
    redacted_input = redact_text(input_text, user_id=user_id)
    assert_redacted(redacted_input)
    trace_id = str(uuid4())
    now = _now()
    with SessionLocal.begin() as db:
        if session_id is not None:
            consent = db.execute(
                select(TrainingConsent).where(
                    TrainingConsent.user_id == user_id,
                    TrainingConsent.session_id == session_id,
                )
            ).scalar_one_or_none()
            if (
                consent is None
                or not consent.enabled
                or consent.revision != consent_revision
                or consent.policy_version != settings.training_consent_policy_version
            ):
                return None
        elif consent_revision != 0:
            return None
        db.add(
            AIGenerationTrace(
                id=trace_id,
                user_id=user_id,
                session_id=session_id,
                status=status,
                source_type="chat",
                input_text=redacted_input,
                output_text="",
                tool_trace_json=None,
                model=model,
                provider=provider,
                generation_params_json=generation_params,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                tool_schema_version=tool_schema_version,
                latency_ms=latency_ms,
                as_of=now,
                error_type=error_type[:128],
                consent_policy_version=settings.training_consent_policy_version,
                redaction_policy_version=settings.training_redaction_policy_version,
                expires_at=now
                + timedelta(days=max(settings.training_trace_retention_days, 1)),
            )
        )
    return trace_id


def submit_feedback(
    user_id: str,
    assistant_message_id: str,
    rating: str,
    issue_labels: list[str],
    comment: str | None,
) -> dict[str, Any]:
    if rating not in {"up", "down"}:
        raise TrainingDataError("rating 仅允许 up/down")
    labels = sorted(set(issue_labels))
    if any(label not in ISSUE_LABELS for label in labels):
        raise TrainingDataError("包含不支持的问题标签")
    cleaned_comment = redact_text((comment or "").strip(), user_id=user_id) or None
    assert_redacted(cleaned_comment or "")
    now = _now()
    with SessionLocal.begin() as db:
        _lock_dataset_lifecycle(db)
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:message_id))"),
                {"message_id": assistant_message_id},
            )
        message = db.execute(
            select(ChatMessage).where(
                ChatMessage.id == assistant_message_id,
                ChatMessage.user_id == user_id,
                ChatMessage.role == "assistant",
            )
        ).scalar_one_or_none()
        if message is None:
            raise TrainingDataError("回答不存在")
        trace = db.execute(
            select(AIGenerationTrace).where(
                AIGenerationTrace.assistant_message_id == assistant_message_id,
                AIGenerationTrace.user_id == user_id,
            )
        ).scalar_one_or_none()
        consent_enabled = bool(
            trace
            and db.execute(
                select(TrainingConsent.enabled).where(
                    TrainingConsent.user_id == user_id,
                    TrainingConsent.session_id == trace.session_id,
                )
            ).scalar_one_or_none()
        )
        if trace is None or not consent_enabled:
            raise TrainingDataError("该回答未授权用于模型改进")
        feedback = db.execute(
            select(AITrainingFeedback).where(
                AITrainingFeedback.user_id == user_id,
                AITrainingFeedback.assistant_message_id == assistant_message_id,
            )
        ).scalar_one_or_none()
        if feedback is None:
            feedback = AITrainingFeedback(
                id=str(uuid4()),
                user_id=user_id,
                assistant_message_id=assistant_message_id,
                trace_id=trace.id,
                rating=rating,
            )
            db.add(feedback)
        feedback.rating = rating
        feedback.issue_labels_json = labels
        feedback.comment = cleaned_comment
        feedback.updated_at = now
        db.flush()
        candidate = db.execute(
            select(TrainingCandidate).where(TrainingCandidate.trace_id == trace.id)
        ).scalar_one_or_none()
        if candidate is None:
            candidate = TrainingCandidate(
                id=str(uuid4()),
                trace_id=trace.id,
                feedback_id=feedback.id,
                status="pending",
                task_type=(
                    "honesty-compliance"
                    if {"missing_data", "unsafe_advice"} & set(labels)
                    else "grounded-response"
                ),
                source_type="chat",
            )
            db.add(candidate)
        else:
            if candidate.status == "approved":
                datasets = db.execute(
                    select(TrainingDataset)
                    .join(
                        TrainingDatasetItem,
                        TrainingDatasetItem.dataset_id == TrainingDataset.id,
                    )
                    .where(TrainingDatasetItem.candidate_id == candidate.id)
                ).scalars().all()
                for dataset in datasets:
                    dataset.status = "deprecated"
                    dataset.deprecated_at = now
                    _remove_artifact(dataset.artifact_path)
                    dataset.artifact_path = None
            candidate.status = "pending"
            candidate.reviewed_by = None
            candidate.reviewed_at = None
        return {
            "id": feedback.id,
            "assistantMessageId": assistant_message_id,
            "rating": rating,
            "issueLabels": labels,
            "comment": cleaned_comment,
            "candidateId": candidate.id,
            "updatedAt": now.isoformat(),
        }


def list_candidates(status: str | None, limit: int = 100) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        stmt = (
            select(TrainingCandidate, AIGenerationTrace, AITrainingFeedback)
            .join(AIGenerationTrace, TrainingCandidate.trace_id == AIGenerationTrace.id)
            .join(AITrainingFeedback, TrainingCandidate.feedback_id == AITrainingFeedback.id)
            .order_by(TrainingCandidate.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
        if status:
            stmt = stmt.where(TrainingCandidate.status == status)
        rows = db.execute(stmt).all()
        return [
            {
                "id": candidate.id,
                "status": candidate.status,
                "taskType": candidate.task_type,
                "sourceType": candidate.source_type,
                "input": trace.input_text,
                "output": trace.output_text,
                "toolTrace": trace.tool_trace_json or [],
                "rating": feedback.rating,
                "issueLabels": feedback.issue_labels_json or [],
                "comment": feedback.comment,
                "idealAnswer": candidate.ideal_answer,
                "qualityLabels": candidate.quality_labels_json or [],
                "reviewNote": candidate.review_note,
                "createdAt": candidate.created_at.isoformat(),
            }
            for candidate, trace, feedback in rows
        ]


def export_user_data(user_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        consents = db.execute(
            select(TrainingConsent).where(TrainingConsent.user_id == user_id)
        ).scalars().all()
        traces = db.execute(
            select(AIGenerationTrace)
            .where(AIGenerationTrace.user_id == user_id)
            .order_by(AIGenerationTrace.created_at)
        ).scalars().all()
        feedback = db.execute(
            select(AITrainingFeedback)
            .where(AITrainingFeedback.user_id == user_id)
            .order_by(AITrainingFeedback.created_at)
        ).scalars().all()
        return {
            "policyVersion": settings.training_consent_policy_version,
            "consents": [
                _consent_data(row, row.session_id)
                for row in consents
            ],
            "traces": [
                {
                    "id": row.id,
                    "sessionId": row.session_id,
                    "status": row.status,
                    "input": row.input_text,
                    "output": row.output_text,
                    "toolTrace": row.tool_trace_json or [],
                    "model": row.model,
                    "provider": row.provider,
                    "generationParams": row.generation_params_json or {},
                    "promptVersion": row.prompt_version,
                    "redactionPolicyVersion": row.redaction_policy_version,
                    "asOf": row.as_of.isoformat() if row.as_of else None,
                    "createdAt": row.created_at.isoformat(),
                }
                for row in traces
            ],
            "feedback": [
                {
                    "id": row.id,
                    "assistantMessageId": row.assistant_message_id,
                    "rating": row.rating,
                    "issueLabels": row.issue_labels_json or [],
                    "comment": row.comment,
                }
                for row in feedback
            ],
        }


def erase_user_data(user_id: str) -> dict[str, int]:
    removed = {"consents": 0, "traces": 0, "feedback": 0, "candidates": 0}
    now = _now()
    with SessionLocal.begin() as db:
        _lock_dataset_lifecycle(db)
        traces = db.execute(
            select(AIGenerationTrace).where(AIGenerationTrace.user_id == user_id)
        ).scalars().all()
        trace_ids = [row.id for row in traces]
        feedback = db.execute(
            select(AITrainingFeedback).where(AITrainingFeedback.user_id == user_id)
        ).scalars().all()
        candidates = (
            db.execute(
                select(TrainingCandidate).where(
                    TrainingCandidate.trace_id.in_(trace_ids)
                )
            ).scalars().all()
            if trace_ids
            else []
        )
        candidate_ids = [row.id for row in candidates]
        if candidate_ids:
            items = db.execute(
                select(TrainingDatasetItem).where(
                    TrainingDatasetItem.candidate_id.in_(candidate_ids)
                )
            ).scalars().all()
            dataset_ids = {item.dataset_id for item in items}
            for dataset_id in dataset_ids:
                dataset = db.get(TrainingDataset, dataset_id)
                if dataset is not None:
                    dataset.status = "deprecated"
                    dataset.deprecated_at = now
                    _remove_artifact(dataset.artifact_path)
                    dataset.artifact_path = None
            for item in items:
                item.candidate_id = None
        for row in candidates:
            db.delete(row)
        for row in feedback:
            db.delete(row)
        for row in traces:
            db.delete(row)
        consents = db.execute(
            select(TrainingConsent).where(TrainingConsent.user_id == user_id)
        ).scalars().all()
        for row in consents:
            db.delete(row)
        removed.update(
            {
                "consents": len(consents),
                "traces": len(traces),
                "feedback": len(feedback),
                "candidates": len(candidates),
            }
        )
    return removed


def purge_expired_traces() -> int:
    now = _now()
    with SessionLocal.begin() as db:
        approved = exists(
            select(TrainingCandidate.id).where(
                TrainingCandidate.trace_id == AIGenerationTrace.id,
                TrainingCandidate.status == "approved",
            )
        )
        rows = db.execute(
            select(AIGenerationTrace).where(
                AIGenerationTrace.expires_at.is_not(None),
                AIGenerationTrace.expires_at < now,
                ~approved,
            )
        ).scalars().all()
        for row in rows:
            db.delete(row)
        return len(rows)


def review_candidate(
    candidate_id: str,
    reviewer_id: str,
    *,
    status: str,
    task_type: str,
    ideal_answer: str | None,
    quality_labels: list[str],
    review_note: str | None,
) -> dict[str, Any]:
    if status not in REVIEW_STATUSES:
        raise TrainingDataError("非法审核状态")
    if task_type not in TASK_TYPES:
        raise TrainingDataError("非法任务类型")
    now = _now()
    with SessionLocal.begin() as db:
        _lock_dataset_lifecycle(db)
        candidate = db.get(TrainingCandidate, candidate_id)
        if candidate is None:
            raise TrainingDataError("候选不存在")
        frozen_membership = db.execute(
            select(TrainingDatasetItem.id)
            .join(
                TrainingDataset,
                TrainingDataset.id == TrainingDatasetItem.dataset_id,
            )
            .where(
                TrainingDatasetItem.candidate_id == candidate_id,
                TrainingDataset.status == "frozen",
            )
            .limit(1)
        ).scalar_one_or_none()
        if frozen_membership is not None:
            raise TrainingDataError("候选已进入冻结数据集，不可修改")
        feedback = db.get(AITrainingFeedback, candidate.feedback_id)
        if status == "approved" and feedback and feedback.rating == "down" and not ideal_answer:
            raise TrainingDataError("差评样本批准前必须填写理想答案")
        cleaned_answer = redact_text((ideal_answer or "").strip()) or None
        cleaned_note = redact_text((review_note or "").strip()) or None
        assert_redacted((cleaned_answer or "", cleaned_note or ""))
        candidate.status = status
        candidate.task_type = task_type
        candidate.ideal_answer = cleaned_answer
        candidate.quality_labels_json = sorted(set(quality_labels))
        candidate.review_note = cleaned_note
        candidate.reviewed_by = reviewer_id
        candidate.reviewed_at = now
        return {"id": candidate.id, "status": status, "reviewedAt": now.isoformat()}


def prompt_fingerprint(prompt: str) -> tuple[str, str]:
    normalized = prompt.strip()
    return "chat-system-v1", hashlib.sha256(normalized.encode()).hexdigest()


def tool_schema_fingerprint(tools: list[dict[str, Any]]) -> str:
    payload = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
