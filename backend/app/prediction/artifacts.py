"""Native-format, checksum-bound prediction model bundles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.prediction.features import FEATURE_SCHEMA_VERSION
from app.prediction.modeling import (
    IsotonicCalibrator,
    TrainedPredictionModel,
)

_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODEL_NAMES = ("classifier", "quantile_p10", "quantile_p50", "quantile_p90")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_estimator(estimator: Any, path: Path, provider: str) -> None:
    if provider == "lightgbm":
        booster = getattr(estimator, "booster_", estimator)
        booster.save_model(str(path))
        return
    if provider == "xgboost":
        estimator.save_model(path)
        return
    raise ValueError("未知模型 provider")


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
    root.mkdir(parents=True, exist_ok=True)
    draft = root / f".{version}.{uuid4().hex}.draft"
    draft.mkdir()
    try:
        extension = "txt" if model.provider == "lightgbm" else "json"
        estimators = (model.classifier, *model.quantile_models)
        files: dict[str, str] = {}
        for name, estimator in zip(_MODEL_NAMES, estimators, strict=True):
            filename = f"{name}.{extension}"
            path = draft / filename
            _save_estimator(estimator, path, model.provider)
            files[filename] = _sha256(path)
        calibrator_path = draft / "calibrator.json"
        calibrator_path.write_text(
            json.dumps(
                {"x": model.calibrator.x, "y": model.calibrator.y},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        files[calibrator_path.name] = _sha256(calibrator_path)
        manifest = {
            "schemaVersion": 2,
            "version": version,
            "provider": model.provider,
            "featureSchemaVersion": FEATURE_SCHEMA_VERSION,
            "dataSha256": data_sha256,
            "files": files,
            "metrics": metrics,
            "promotionEligible": bool(
                metrics.get("promotionEligible") is True
            ),
            "artifactStatus": (
                "validated_unregistered"
                if metrics.get("promotionEligible") is True
                else "candidate_unregistered"
            ),
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
        manifest_path = draft / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(draft, target_dir)
        published_manifest = target_dir / "manifest.json"
        return {
            **manifest,
            "artifactPath": str(published_manifest),
            "manifestSha256": _sha256(published_manifest),
        }
    except Exception:
        shutil.rmtree(draft, ignore_errors=True)
        raise


def _verified_bundle(
    manifest_path: str,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    root = Path(settings.prediction_artifact_dir).resolve()
    raw_path = Path(manifest_path)
    if raw_path.is_symlink():
        raise ValueError("模型 manifest 路径不受信任")
    path = raw_path.resolve()
    if root not in path.parents or path.name != "manifest.json":
        raise ValueError("模型 manifest 路径不受信任")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("模型 manifest 类型不受信任")
    try:
        manifest_bytes = path.read_bytes()
    except OSError as exc:
        raise ValueError("模型 manifest 不可读") from exc
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("模型 manifest checksum 不匹配")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError("模型 manifest 不可读") from exc
    if (
        manifest.get("schemaVersion") != 2
        or manifest.get("featureSchemaVersion") != FEATURE_SCHEMA_VERSION
        or manifest.get("provider") not in {"lightgbm", "xgboost"}
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ValueError("模型 manifest schema 不受支持")
    expected_names = {
        f"{name}.{'txt' if manifest['provider'] == 'lightgbm' else 'json'}"
        for name in _MODEL_NAMES
    } | {"calibrator.json"}
    if set(manifest["files"]) != expected_names:
        raise ValueError("模型 manifest 文件集合不完整")
    verified_files: dict[str, bytes] = {}
    for filename, checksum in manifest["files"].items():
        file_path = path.parent / filename
        file_stat = file_path.lstat()
        if not stat.S_ISREG(file_stat.st_mode) or file_path.is_symlink():
            raise ValueError(f"模型文件类型不受信任: {filename}")
        file_bytes = file_path.read_bytes()
        if hashlib.sha256(file_bytes).hexdigest() != checksum:
            raise ValueError(f"模型文件 checksum 不匹配: {filename}")
        verified_files[filename] = file_bytes
    return manifest, verified_files


def verify_model_bundle(
    manifest_path: str,
    *,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    manifest, _ = _verified_bundle(
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    return manifest


def load_model_bundle(
    manifest_path: str,
    *,
    expected_manifest_sha256: str,
) -> TrainedPredictionModel:
    manifest, verified_files = _verified_bundle(
        manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    with TemporaryDirectory(prefix="verified-model-") as directory:
        root = Path(directory)
        for filename, file_bytes in verified_files.items():
            (root / filename).write_bytes(file_bytes)
        calibrator = json.loads(verified_files["calibrator.json"])
        portable_calibrator = IsotonicCalibrator(
            x=[float(value) for value in calibrator["x"]],
            y=[float(value) for value in calibrator["y"]],
        )
        provider = manifest["provider"]
        if provider == "lightgbm":
            from lightgbm import Booster

            classifier = Booster(model_file=str(root / "classifier.txt"))
            quantiles = tuple(
                Booster(model_file=str(root / f"{name}.txt"))
                for name in ("quantile_p10", "quantile_p50", "quantile_p90")
            )
        else:
            from xgboost import XGBClassifier, XGBRegressor

            classifier = XGBClassifier()
            classifier.load_model(root / "classifier.json")
            quantile_models = []
            for name in ("quantile_p10", "quantile_p50", "quantile_p90"):
                model = XGBRegressor()
                model.load_model(root / f"{name}.json")
                quantile_models.append(model)
            quantiles = tuple(quantile_models)
    return TrainedPredictionModel(
        provider=provider,
        classifier=classifier,
        calibrator=portable_calibrator,
        quantile_models=quantiles,
    )
