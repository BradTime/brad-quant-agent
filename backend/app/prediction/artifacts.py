"""Checksum-bound internal model artifact storage."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import joblib

from app.core.config import settings
from app.prediction.features import FEATURE_SCHEMA_VERSION
from app.prediction.modeling import TrainedPredictionModel

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_model_bundle(
    model: TrainedPredictionModel,
    *,
    version: str,
    metrics: dict[str, Any],
    data_sha256: str,
) -> dict[str, Any]:
    if _VERSION_RE.fullmatch(version) is None:
        raise ValueError("模型版本只能包含字母、数字、点、下划线和连字符")
    root = Path(settings.prediction_artifact_dir).resolve()
    target_dir = root / version
    if target_dir.exists():
        raise ValueError("模型版本已存在，不允许覆盖")
    target_dir.mkdir(parents=True, exist_ok=False)
    model_path = target_dir / "model.joblib"
    try:
        with NamedTemporaryFile(
            dir=target_dir,
            prefix=".model-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        joblib.dump(model, temporary_path)
        os.replace(temporary_path, model_path)
        checksum = _sha256(model_path)
        manifest = {
            "schemaVersion": 1,
            "version": version,
            "provider": model.provider,
            "featureSchemaVersion": FEATURE_SCHEMA_VERSION,
            "dataSha256": data_sha256,
            "modelSha256": checksum,
            "metrics": metrics,
            "promotionEligible": False,
            "artifactStatus": "candidate_unregistered",
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "lightgbm",
                    "xgboost",
                    "scikit-learn",
                    "numpy",
                )
            },
        }
        manifest_path = target_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_checksum = _sha256(manifest_path)
        return {
            **manifest,
            "artifactPath": str(model_path),
            "manifestPath": str(manifest_path),
            "manifestSha256": manifest_checksum,
        }
    except Exception:
        for path in target_dir.glob("*"):
            path.unlink(missing_ok=True)
        target_dir.rmdir()
        raise


def verify_model_bundle(
    artifact_path: str,
    *,
    expected_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(settings.prediction_artifact_dir).resolve()
    path = Path(artifact_path).resolve()
    if root not in path.parents or path.name != "model.joblib":
        raise ValueError("模型 artifact 路径不受信任")
    if _sha256(path) != expected_sha256:
        raise ValueError("模型 artifact checksum 不匹配")
    manifest_path = path.with_name("manifest.json")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ValueError("模型 manifest 不可读") from exc
    manifest_checksum = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_checksum != expected_manifest_sha256:
        raise ValueError("模型 manifest checksum 不匹配")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("模型 manifest 不可读") from exc
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("modelSha256") != expected_sha256
        or manifest.get("featureSchemaVersion") != FEATURE_SCHEMA_VERSION
    ):
        raise ValueError("模型 manifest 与可信引用不匹配")
    return manifest
