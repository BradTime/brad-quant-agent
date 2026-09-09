"""Trusted M3 model registration, promotion, and forecast persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.json_payload import dump_envelope, load_envelope
from app.core.tz import MARKET_TZ
from app.db.session import SessionLocal
from app.models.prediction import (
    PredictionForecast,
    PredictionModelRun,
    PredictionPromotionAudit,
)
from app.prediction.artifacts import (
    load_model_bundle,
    save_model_bundle,
    verify_model_bundle,
)
from app.prediction.features import (
    FEATURE_SCHEMA_VERSION,
    PredictionExample,
    PredictionFeature,
)
from app.prediction.modeling import ModelProvider, train_prediction_model
from app.prediction.orchestration import evaluate_walk_forward


def _data_sha256(
    examples: list[PredictionExample], evidence_sha256: str
) -> str:
    digest = hashlib.sha256()
    digest.update(evidence_sha256.encode())
    for row in sorted(examples, key=lambda item: (item.signal_date, item.code)):
        digest.update(
            json.dumps(
                {
                    "code": row.code,
                    "signalDate": row.signal_date.isoformat(),
                    "labelDate": row.label_date.isoformat(),
                    "features": row.features,
                    "nextReturn": row.next_return,
                    "nextUp": row.next_up,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    return digest.hexdigest()


def register_candidate(
    user_id: str | None,
    *,
    version: str,
    provider: ModelProvider,
    examples: list[PredictionExample],
    regime_by_date: dict[date, str],
    evidence_sha256: str,
    minimum_train_dates: int = 252,
    validation_dates: int = 63,
    embargo_dates: int = 5,
    max_folds: int = 5,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("训练样本不能为空")
    if len(evidence_sha256) != 64:
        raise ValueError("训练证据 checksum 无效")
    data_sha256 = _data_sha256(examples, evidence_sha256)
    run_id = str(uuid4())
    expected_artifact_path = str(
        Path(settings.prediction_artifact_dir).resolve()
        / version
        / "manifest.json"
    )
    try:
        with SessionLocal.begin() as session:
            existing = session.execute(
                select(PredictionModelRun)
                .where(PredictionModelRun.version == version)
                .with_for_update()
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    PredictionModelRun(
                        id=run_id,
                        user_id=user_id,
                        version=version,
                        provider=provider,
                        status="registering",
                        feature_schema_version=FEATURE_SCHEMA_VERSION,
                        data_sha256=data_sha256,
                        artifact_path=expected_artifact_path,
                        artifact_sha256=None,
                        metrics_json=dump_envelope(
                            {
                                "status": "evaluating",
                                "evidenceSha256": evidence_sha256,
                            }
                        ),
                        training_start=min(
                            item.signal_date for item in examples
                        ),
                        training_end=max(
                            item.label_date for item in examples
                        ),
                        is_champion=False,
                    )
                )
            else:
                raise ValueError("模型版本已存在或正在注册")
    except IntegrityError:
        raise ValueError("模型版本已存在或正在注册") from None
    report = evaluate_walk_forward(
        examples,
        regime_by_date=regime_by_date,
        provider=provider,
        minimum_train_dates=minimum_train_dates,
        validation_dates=validation_dates,
        embargo_dates=embargo_dates,
        max_folds=max_folds,
    )
    report["evidenceSha256"] = evidence_sha256
    promotion_eligible = report["promotionEligible"]
    with SessionLocal.begin() as session:
        stored = session.execute(
            select(PredictionModelRun)
            .where(PredictionModelRun.id == run_id)
            .with_for_update()
        ).scalar_one()
        stored.metrics_json = dump_envelope(report)
        if not promotion_eligible:
            stored.status = "rejected"
            stored.artifact_path = None
    artifact_sha256 = None
    status = "rejected"
    if promotion_eligible:
        try:
            model = train_prediction_model(
                examples,
                provider=provider,
                seed=42,
            )
            artifact = save_model_bundle(
                model,
                version=version,
                metrics=report,
                data_sha256=data_sha256,
            )
            artifact_path = artifact["artifactPath"]
            artifact_sha256 = artifact["manifestSha256"]
            verify_model_bundle(
                artifact_path,
                expected_manifest_sha256=artifact_sha256,
            )
            with SessionLocal.begin() as session:
                stored = session.execute(
                    select(PredictionModelRun)
                    .where(PredictionModelRun.id == run_id)
                    .with_for_update()
                ).scalar_one()
                stored.artifact_path = artifact_path
                stored.artifact_sha256 = artifact_sha256
                stored.status = "validated"
            status = "validated"
        except Exception:
            # Keep "registering" so an operator retry with identical evidence
            # can resume evaluation or bind a fully published native bundle.
            raise
    return {
        "id": run_id,
        "version": version,
        "provider": provider,
        "status": status,
        "promotionEligible": report["promotionEligible"],
        "metrics": report,
        "dataSha256": data_sha256,
        "artifactSha256": artifact_sha256,
    }


def recover_registration(version: str) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        row = session.execute(
            select(PredictionModelRun)
            .where(PredictionModelRun.version == version)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or row.status != "registering":
            raise ValueError("没有可恢复的 registering 模型")
        metrics = load_envelope(
            row.metrics_json,
            expect="dict",
            field="metrics_json",
        )
        if not row.artifact_sha256:
            row.status = "failed"
            row.artifact_path = None
            return {"id": row.id, "version": row.version, "status": "failed"}
        if not row.artifact_path or not Path(row.artifact_path).is_file():
            row.status = "failed"
            row.artifact_path = None
            return {"id": row.id, "version": row.version, "status": "failed"}
        checksum = row.artifact_sha256
        manifest = verify_model_bundle(
            row.artifact_path,
            expected_manifest_sha256=checksum,
        )
        if (
            manifest.get("version") != row.version
            or manifest.get("provider") != row.provider
            or manifest.get("dataSha256") != row.data_sha256
            or manifest.get("metrics") != metrics
        ):
            row.status = "failed"
            row.artifact_path = None
            return {"id": row.id, "version": row.version, "status": "failed"}
        row.artifact_sha256 = checksum
        row.status = "validated"
        return {
            "id": row.id,
            "version": row.version,
            "status": "validated",
            "artifactSha256": checksum,
        }


def promote_candidate(
    run_id: str,
    *,
    promoted_by_user_id: str,
) -> dict[str, Any]:
    try:
        with SessionLocal.begin() as session:
            row = session.execute(
                select(PredictionModelRun)
                .where(PredictionModelRun.id == run_id)
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise ValueError("模型候选不存在")
            metrics = load_envelope(
                row.metrics_json,
                expect="dict",
                field="metrics_json",
            )
            if (
                row.status != "validated"
                or metrics.get("promotionEligible") is not True
                or not row.artifact_path
                or not row.artifact_sha256
            ):
                raise ValueError("模型候选未通过 OOS/状态覆盖门禁")
            manifest = verify_model_bundle(
                row.artifact_path,
                expected_manifest_sha256=row.artifact_sha256,
            )
            if (
                manifest.get("version") != row.version
                or manifest.get("provider") != row.provider
                or manifest.get("dataSha256") != row.data_sha256
                or manifest.get("metrics") != metrics
                or manifest.get("promotionEligible") is not True
                or manifest.get("artifactStatus") != "validated_unregistered"
            ):
                raise ValueError("模型 artifact 与注册门禁证据不匹配")
            champions = session.execute(
                select(PredictionModelRun)
                .where(PredictionModelRun.is_champion.is_(True))
                .with_for_update()
            ).scalars().all()
            previous_id = champions[0].id if champions else None
            for champion in champions:
                champion.is_champion = False
            session.flush()
            row.is_champion = True
            row.status = "champion"
            session.add(
                PredictionPromotionAudit(
                    id=str(uuid4()),
                    model_run_id=row.id,
                    previous_model_run_id=previous_id,
                    promoted_by_user_id=promoted_by_user_id,
                    promoted_by_user_id_snapshot=promoted_by_user_id,
                    artifact_sha256=row.artifact_sha256,
                )
            )
            result = {
                "id": row.id,
                "version": row.version,
                "provider": row.provider,
                "status": row.status,
                "artifactSha256": row.artifact_sha256,
            }
        return result
    except IntegrityError as exc:
        raise ValueError("已有并发 Champion 晋级，请刷新后重试") from exc


def _champion(session) -> PredictionModelRun:
    row = session.execute(
        select(PredictionModelRun)
        .where(PredictionModelRun.is_champion.is_(True))
        .order_by(PredictionModelRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if (
        row is None
        or not row.artifact_path
        or not row.artifact_sha256
    ):
        raise ValueError("当前没有可信 Champion 模型")
    return row


def infer_and_store(
    examples: list[PredictionFeature],
) -> list[dict[str, Any]]:
    if not examples:
        return []
    with SessionLocal() as session:
        champion = _champion(session)
        model_run_id = champion.id
        artifact_path = champion.artifact_path
        artifact_sha256 = champion.artifact_sha256
    model = load_model_bundle(
        artifact_path,
        expected_manifest_sha256=artifact_sha256,
    )
    predictions = model.predict(examples)
    output: list[dict[str, Any]] = []
    with SessionLocal.begin() as session:
        for example, prediction in zip(examples, predictions, strict=True):
            feature_sha256 = hashlib.sha256(
                json.dumps(
                    example.features,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            row = PredictionForecast(
                id=str(uuid4()),
                model_run_id=model_run_id,
                code=example.code,
                signal_date=example.signal_date,
                probability_up=prediction["probabilityUp"],
                return_p10=prediction["returnP10"],
                return_p50=prediction["returnP50"],
                return_p90=prediction["returnP90"],
                feature_sha256=feature_sha256,
            )
            session.add(row)
            output.append(
                {
                    "code": example.code,
                    "signalDate": example.signal_date.isoformat(),
                    **prediction,
                    "modelRunId": model_run_id,
                    "featureSha256": feature_sha256,
                }
            )
        try:
            session.flush()
        except IntegrityError as exc:
            raise ValueError("该模型和日期的预测已存在") from exc
    return output


def get_prediction_in_session(
    session,
    code: str,
    *,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    cutoff = None
    if as_of is None:
        champion = _champion(session)
    else:
        cutoff = datetime.combine(
            as_of, time.max, tzinfo=MARKET_TZ
        ).astimezone(UTC)
        audit = session.execute(
            select(PredictionPromotionAudit)
            .where(PredictionPromotionAudit.created_at <= cutoff)
            .order_by(PredictionPromotionAudit.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if audit is None:
            return None
        champion = session.get(PredictionModelRun, audit.model_run_id)
        if champion is None:
            return None
    conditions = [
        PredictionForecast.model_run_id == champion.id,
        PredictionForecast.code == code,
    ]
    if as_of is not None:
        conditions.append(PredictionForecast.signal_date <= as_of)
        conditions.append(PredictionForecast.inferred_at <= cutoff)
    forecast = session.execute(
        select(PredictionForecast)
        .where(*conditions)
        .order_by(PredictionForecast.signal_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if forecast is None:
        return None
    return {
        "code": forecast.code,
        "signalDate": forecast.signal_date.isoformat(),
        "probabilityUp": forecast.probability_up,
        "probabilityDown": 1 - forecast.probability_up,
        "returnInterval80": {
            "low": forecast.return_p10,
            "median": forecast.return_p50,
            "high": forecast.return_p90,
        },
        "featureSha256": forecast.feature_sha256,
        "model": {
            "runId": champion.id,
            "version": champion.version,
            "provider": champion.provider,
            "artifactSha256": champion.artifact_sha256,
        }
    }


def get_prediction(
    code: str,
    *,
    as_of: date | None = None,
) -> dict[str, Any] | None:
    with SessionLocal() as session:
        return get_prediction_in_session(session, code, as_of=as_of)
