"""Deterministic, audited JSONL dataset construction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text

from app.ai.tools import TOOLS, validate_tool_arguments
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.training import (
    AIGenerationTrace,
    AITrainingFeedback,
    TrainingCandidate,
    TrainingDataset,
    TrainingDatasetItem,
)
from app.services.training_data import TrainingDataError
from app.services.training_redaction import assert_redacted

SCHEMA_VERSION = 1
REQUIRED_TASK_TYPES = {
    "tool-routing",
    "grounded-response",
    "honesty-compliance",
}


def _normalized_intent(value: str) -> str:
    compact = " ".join(value.lower().split())
    return re.sub(r"\d+(?:\.\d+)?", "<N>", compact)


@lru_cache(maxsize=1)
def _holdout_fingerprints() -> set[str]:
    path = Path(__file__).resolve().parents[2] / "tests" / "golden_questions.json"
    if not path.exists():
        raise TrainingDataError("缺少版本化黄金 holdout 清单")
    rows = json.loads(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for row in rows:
        question = str(row["question"])
        for text_value in (question, _normalized_intent(question)):
            values.add(hashlib.sha256(text_value.encode()).hexdigest())
    return values


def _stable_split(trace: AIGenerationTrace) -> str:
    # A session is the minimum indivisible group. Similarity/duplicate audits
    # may merge more records but must never split one conversation.
    group = f"{trace.user_id}:{trace.session_id or trace.id}"
    bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 100
    return "validation" if bucket < 20 else "train"


def _example(
    candidate: TrainingCandidate,
    trace: AIGenerationTrace,
    feedback: AITrainingFeedback,
) -> dict[str, Any]:
    target = (candidate.ideal_answer or trace.output_text).strip()
    if not target:
        raise TrainingDataError(f"候选 {candidate.id} 缺少训练目标")
    if feedback.rating == "down" and not candidate.ideal_answer:
        raise TrainingDataError(f"差评候选 {candidate.id} 缺少理想答案")
    labels = set(candidate.quality_labels_json or [])
    if labels & {"golden", "holdout", "evaluation"}:
        raise TrainingDataError(f"候选 {candidate.id} 属于保留评测集")
    input_hashes = {
        hashlib.sha256(trace.input_text.encode()).hexdigest(),
        hashlib.sha256(_normalized_intent(trace.input_text).encode()).hexdigest(),
    }
    if input_hashes & _holdout_fingerprints():
        raise TrainingDataError(f"候选 {candidate.id} 与黄金 holdout 重叠")
    tool_trace = trace.tool_trace_json or []
    _validate_tool_trace(tool_trace)
    provenance = _source_provenance(tool_trace)
    example = {
        "schemaVersion": SCHEMA_VERSION,
        "taskType": candidate.task_type,
        "messages": [
            {"role": "user", "content": trace.input_text},
            {"role": "assistant", "content": target},
        ],
        "toolTrace": tool_trace,
        "metadata": {
            "candidateRef": hashlib.sha256(candidate.id.encode()).hexdigest()[:16],
            "sourceType": candidate.source_type,
            "promptVersion": trace.prompt_version,
            "promptHash": trace.prompt_hash,
            "toolSchemaVersion": trace.tool_schema_version,
            "model": trace.model,
            "provider": trace.provider,
            "generationParams": trace.generation_params_json or {},
            "asOf": trace.as_of.isoformat() if trace.as_of else None,
            "consentPolicyVersion": trace.consent_policy_version,
            "redactionPolicyVersion": trace.redaction_policy_version,
            "qualityLabels": candidate.quality_labels_json or [],
            "feedback": feedback.rating,
            "reviewerRef": (
                hashlib.sha256(candidate.reviewed_by.encode()).hexdigest()[:16]
                if candidate.reviewed_by
                else None
            ),
            "reviewedAt": (
                candidate.reviewed_at.isoformat() if candidate.reviewed_at else None
            ),
            "provenance": {
                "userContent": "explicit-user-opt-in",
                "toolSources": provenance,
            },
            "license": "user-consented-model-improvement",
        },
    }
    assert_redacted(example)
    return example


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_tool_trace(tool_trace: list[dict[str, Any]]) -> None:
    known = {tool["function"]["name"] for tool in TOOLS}
    for call in tool_trace:
        name = call.get("name")
        arguments = call.get("args")
        if name not in known or not isinstance(arguments, dict):
            raise TrainingDataError(f"非法工具轨迹: {name}")
        try:
            validate_tool_arguments(str(name), arguments)
        except ValueError as exc:
            raise TrainingDataError(f"工具 {name} 参数无效: {exc}") from exc


def _source_provenance(tool_trace: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() == "source" and isinstance(item, str):
                    sources.add(item.strip().lower())
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(tool_trace)
    if not tool_trace:
        return [{"source": "none", "licenseClass": "no-external-tool-data"}]
    approved = {
        source.strip().lower()
        for source in settings.training_approved_tool_sources.split(",")
        if source.strip()
    }
    unknown = sorted(source for source in sources if source not in approved)
    if unknown:
        raise TrainingDataError("工具结果包含未批准来源: " + ",".join(unknown))
    if not sources:
        raise TrainingDataError("工具结果缺少可验证 source")
    return [
        {"source": source, "licenseClass": "configured-approved-source"}
        for source in sorted(sources)
    ]


def _approved_rows(db) -> list[tuple[TrainingCandidate, AIGenerationTrace, AITrainingFeedback]]:
    return list(
        db.execute(
            select(TrainingCandidate, AIGenerationTrace, AITrainingFeedback)
            .join(AIGenerationTrace, TrainingCandidate.trace_id == AIGenerationTrace.id)
            .join(AITrainingFeedback, TrainingCandidate.feedback_id == AITrainingFeedback.id)
            .where(TrainingCandidate.status == "approved")
            .order_by(TrainingCandidate.created_at, TrainingCandidate.id)
        ).all()
    )


def audit_candidates() -> dict[str, Any]:
    errors: list[str] = []
    hashes: set[str] = set()
    counts: Counter[str] = Counter()
    with SessionLocal() as db:
        rows = _approved_rows(db)
        for candidate, trace, feedback in rows:
            try:
                example = _example(candidate, trace, feedback)
                payload_hash = hashlib.sha256(_canonical_json(example).encode()).hexdigest()
                if payload_hash in hashes:
                    errors.append(f"{candidate.id}: duplicate")
                hashes.add(payload_hash)
                counts[candidate.task_type] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate.id}: {exc}")
    return {
        "ok": not errors,
        "approved": len(rows),
        "taskCounts": dict(sorted(counts.items())),
        "errors": errors,
    }


def build_dataset(version: str, created_by: str | None = None) -> dict[str, Any]:
    audit = audit_candidates()
    if not audit["ok"]:
        raise TrainingDataError("数据审计失败: " + "; ".join(audit["errors"][:5]))
    root = Path(settings.training_artifact_dir).resolve()
    dataset_dir = root / version
    if root not in dataset_dir.parents:
        raise TrainingDataError("非法数据集版本路径")
    root.mkdir(parents=True, exist_ok=True)
    temp_dir = root / f".{version}.{uuid4().hex}.tmp"
    dataset_id = str(uuid4())
    published_final = False
    try:
        with SessionLocal.begin() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtext('training-dataset-publication'))"
                    )
                )
            if db.execute(
                select(TrainingDataset.id).where(TrainingDataset.version == version)
            ).scalar_one_or_none():
                raise TrainingDataError("数据集版本已存在且不可覆盖")
            if dataset_dir.exists():
                raise TrainingDataError("数据集 artifact 已存在且不可覆盖")
            rows = _approved_rows(db)
            if not rows:
                raise TrainingDataError("没有已批准候选")
            prepared: list[
                tuple[TrainingCandidate, str, str, dict[str, Any]]
            ] = []
            seen: set[str] = set()
            for candidate, trace, feedback in rows:
                example = _example(candidate, trace, feedback)
                payload = _canonical_json(example)
                payload_hash = hashlib.sha256(payload.encode()).hexdigest()
                if payload_hash in seen:
                    continue
                seen.add(payload_hash)
                prepared.append(
                    (candidate, _stable_split(trace), payload_hash, example)
                )

            temp_dir.mkdir(mode=0o700)
            paths = {
                "train": temp_dir / "train.jsonl",
                "validation": temp_dir / "validation.jsonl",
            }
            for split, path in paths.items():
                with path.open("x", encoding="utf-8") as handle:
                    for _candidate, row_split, _payload_hash, example in prepared:
                        if row_split == split:
                            handle.write(_canonical_json(example) + "\n")
            counts = Counter(split for _candidate, split, _hash, _example in prepared)
            checksum = hashlib.sha256(
                paths["train"].read_bytes() + paths["validation"].read_bytes()
            ).hexdigest()
            manifest = {
                "schemaVersion": SCHEMA_VERSION,
                "version": version,
                "createdAt": datetime.now(UTC).isoformat(),
                "counts": dict(counts),
                "taskCounts": audit["taskCounts"],
                "checksumSha256": checksum,
                "files": {split: path.name for split, path in paths.items()},
            }
            manifest_path = temp_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            for path in (*paths.values(), manifest_path):
                os.chmod(path, 0o600)
            dataset = TrainingDataset(
                id=dataset_id,
                version=version,
                status="draft",
                schema_version=SCHEMA_VERSION,
                manifest_json=manifest,
                checksum_sha256=checksum,
                artifact_path=str(dataset_dir / "train.jsonl"),
                train_count=counts["train"],
                validation_count=counts["validation"],
                created_by=created_by,
                frozen_at=None,
            )
            db.add(dataset)
            db.flush()
            for ordinal, (
                candidate,
                split,
                payload_hash,
                _example_value,
            ) in enumerate(prepared):
                db.add(
                    TrainingDatasetItem(
                        id=str(uuid4()),
                        dataset_id=dataset.id,
                        candidate_id=candidate.id,
                        split=split,
                        ordinal=ordinal,
                        payload_hash=payload_hash,
                    )
                )
            os.replace(temp_dir, dataset_dir)
            published_final = True
            dataset.status = "frozen"
            dataset.frozen_at = datetime.now(UTC)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if published_final:
            shutil.rmtree(dataset_dir, ignore_errors=True)
        raise
    return {
        "id": dataset_id,
        "version": version,
        "status": "frozen",
        "trainCount": counts["train"],
        "validationCount": counts["validation"],
        "checksumSha256": checksum,
        "artifactDir": str(dataset_dir),
    }


def readiness() -> dict[str, Any]:
    with SessionLocal() as db:
        total = int(
            db.execute(
                select(func.count()).select_from(TrainingCandidate).where(
                    TrainingCandidate.status == "approved"
                )
            ).scalar_one()
        )
        task_rows = db.execute(
            select(TrainingCandidate.task_type, func.count())
            .where(TrainingCandidate.status == "approved")
            .group_by(TrainingCandidate.task_type)
        ).all()
    tasks = {task: int(count) for task, count in task_rows}
    estimated_validation = total // 5
    reasons: list[str] = []
    if total < settings.training_readiness_min_approved:
        reasons.append("approved_samples_below_minimum")
    if any(
        tasks.get(task, 0) < settings.training_readiness_min_per_task
        for task in REQUIRED_TASK_TYPES
    ):
        reasons.append("task_coverage_below_minimum")
    if estimated_validation < settings.training_readiness_min_validation:
        reasons.append("validation_samples_below_minimum")
    return {
        "ready": not reasons,
        "approved": total,
        "taskCounts": tasks,
        "estimatedValidation": estimated_validation,
        "thresholds": {
            "approved": settings.training_readiness_min_approved,
            "perTask": settings.training_readiness_min_per_task,
            "validation": settings.training_readiness_min_validation,
        },
        "reasons": reasons,
    }


def dataset_info(version: str) -> dict[str, Any]:
    with SessionLocal() as db:
        dataset = db.execute(
            select(TrainingDataset).where(TrainingDataset.version == version)
        ).scalar_one_or_none()
        if dataset is None:
            raise TrainingDataError("数据集版本不存在")
        artifact = Path(dataset.artifact_path) if dataset.artifact_path else None
        validation = artifact.parent / "validation.jsonl" if artifact else None
        checksum_ok = False
        if artifact and validation and artifact.exists() and validation.exists():
            actual = hashlib.sha256(
                artifact.read_bytes() + validation.read_bytes()
            ).hexdigest()
            checksum_ok = actual == dataset.checksum_sha256
        return {
            "id": dataset.id,
            "version": dataset.version,
            "status": dataset.status,
            "trainCount": dataset.train_count,
            "validationCount": dataset.validation_count,
            "checksumSha256": dataset.checksum_sha256,
            "checksumOk": checksum_ok,
            "artifactDir": str(artifact.parent) if artifact else None,
            "manifest": dataset.manifest_json or {},
        }
