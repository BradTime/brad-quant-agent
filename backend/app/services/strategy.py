"""Tenant-scoped strategy heads and append-only executable definitions."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.json_payload import (
    JsonCorruptError,
    dump_envelope,
    load_envelope,
)
from app.db.session import SessionLocal
from app.models.strategy import Strategy, StrategyVersion
from app.services.backtest_run import strategy_catalog
from app.services.strategy_sandbox import PROTOCOL_VERSION, validate_source

ALLOWED_BUILTIN_TYPES = frozenset(
    {
        "dual_ma",
        "rsi",
        "boll",
        "momentum",
        "donchian_breakout",
        "xs_momentum",
        "zscore_reversion",
        "composite_mf",
        "flow_surge",
        "fundamental_quality",
    }
)
STRATEGY_STATUSES = frozenset({"draft", "active", "disabled"})
DEFINITION_TYPES = frozenset({"builtin", "custom_python"})
CUSTOM_BUILTIN_TYPE = "custom_python"
MAX_CUSTOM_PARAMS_BYTES = 20_000
BUILTIN_IMPLEMENTATION_VERSION = "builtin-v1"
CUSTOM_IMPLEMENTATION_VERSION = "sandbox-signal-v1"


class StrategyConflictError(RuntimeError):
    """A concurrent definition write lost the version-number race."""

_CATEGORY_BY_BUILTIN = {
    "dual_ma": "trend_following",
    "rsi": "mean_reversion",
    "boll": "mean_reversion",
    "momentum": "momentum",
    "donchian_breakout": "trend_following",
    "xs_momentum": "momentum",
    "zscore_reversion": "mean_reversion",
    "composite_mf": "multi_factor",
    "flow_surge": "event",
    "fundamental_quality": "multi_factor",
}


def _catalog_by_type() -> dict[str, dict]:
    return {item["type"]: item for item in strategy_catalog()}


def validate_params(
    builtin_type: str,
    params: dict[str, Any] | None,
) -> tuple[str, dict[str, int | float]]:
    """Validate parameter keys, numeric types, and catalog ranges."""
    catalog = _catalog_by_type()
    if builtin_type not in ALLOWED_BUILTIN_TYPES or builtin_type not in catalog:
        allowed = ", ".join(sorted(ALLOWED_BUILTIN_TYPES))
        raise ValueError(f"builtin_type 只允许: {allowed}")

    supplied = params or {}
    specs = {spec["key"]: spec for spec in catalog[builtin_type]["params"]}
    unknown = sorted(set(supplied) - set(specs))
    if unknown:
        raise ValueError(f"未知策略参数: {', '.join(unknown)}")

    normalized: dict[str, int | float] = {}
    for key, spec in specs.items():
        value = supplied.get(key, spec["default"])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"参数 {key} 必须是数字")
        if not math.isfinite(float(value)):
            raise ValueError(f"参数 {key} 必须是有限数字")
        if spec["type"] == "int":
            if type(value) is not int:
                raise ValueError(f"参数 {key} 必须是整数")
            normalized[key] = value
        else:
            normalized[key] = float(value)

        minimum = spec.get("min")
        maximum = spec.get("max")
        if minimum is not None and normalized[key] < minimum:
            raise ValueError(f"参数 {key} 超出允许范围 [{minimum}, {maximum}]")
        if maximum is not None and normalized[key] > maximum:
            raise ValueError(f"参数 {key} 超出允许范围 [{minimum}, {maximum}]")

    if builtin_type == "dual_ma" and normalized["fast"] >= normalized["slow"]:
        raise ValueError("参数 fast 必须小于 slow")
    if builtin_type == "rsi" and normalized["low"] >= normalized["high"]:
        raise ValueError("参数 low 必须小于 high")
    if (
        builtin_type == "zscore_reversion"
        and normalized["entryZ"] >= normalized["exitZ"]
    ):
        raise ValueError("参数 entryZ 必须小于 exitZ")
    if builtin_type == "composite_mf" and (
        normalized["wMom"] + normalized["wLowVol"] + normalized["wLiq"] <= 0
    ):
        raise ValueError("多因子权重之和必须大于 0")
    if builtin_type == "fundamental_quality" and (
        normalized["wValue"] + normalized["wQuality"] <= 0
    ):
        raise ValueError("价值质量权重之和必须大于 0")

    return _CATEGORY_BY_BUILTIN[builtin_type], normalized


def validate_definition(
    definition_type: str,
    builtin_type: str | None,
    params: dict[str, Any] | None,
    source_code: str | None,
) -> tuple[str, str, dict[str, Any], str | None, str]:
    if definition_type not in DEFINITION_TYPES:
        raise ValueError("definition_type 只允许 builtin/custom_python")
    if definition_type == "builtin":
        if not builtin_type or source_code is not None:
            raise ValueError("内置策略必须提供 builtin_type 且不能提供 source_code")
        category, normalized = validate_params(builtin_type, params)
        normalized_source = None
        stored_type = builtin_type
    else:
        if builtin_type not in {None, CUSTOM_BUILTIN_TYPE} or not source_code:
            raise ValueError("自定义策略必须提供 source_code 且不能提供 builtin_type")
        normalized_source = validate_source(source_code)
        normalized = params or {}
        if len(normalized) > 100:
            raise ValueError("自定义策略 params 不得超过 100 项")
        for key, value in normalized.items():
            if (
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("自定义策略 params 仅允许有限数字参数")
        try:
            encoded_params = json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("自定义策略 params 必须是有限 JSON 数据") from exc
        if len(encoded_params) > MAX_CUSTOM_PARAMS_BYTES:
            raise ValueError(
                f"自定义策略 params 不得超过 {MAX_CUSTOM_PARAMS_BYTES} bytes"
            )
        category = "custom"
        stored_type = CUSTOM_BUILTIN_TYPE
    canonical = json.dumps(
        {
            "definitionType": definition_type,
            "builtinType": stored_type,
            "params": normalized,
            "sourceCode": normalized_source,
            "protocolVersion": PROTOCOL_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return category, stored_type, normalized, normalized_source, digest


def _loads_params(raw: Any) -> dict[str, Any]:
    """Decode params envelope; corrupt data raises JsonCorruptError."""
    if raw is None or raw == "" or raw == {}:
        return {}
    value = load_envelope(raw, expect="dict", field="params_json")
    if not isinstance(value, dict):
        raise JsonCorruptError("params payload must be an object", field="params_json")
    return value  # type: ignore[return-value]


def _dump_params(params: dict[str, Any]) -> dict:
    return dump_envelope(params)


def _serialize(row: Strategy, current: StrategyVersion | None = None) -> dict:
    out: dict[str, Any] = {
        "id": row.id,
        "userId": row.user_id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "builtinType": row.builtin_type,
        "definitionType": row.definition_type,
        "currentVersion": row.current_version,
        "protocolVersion": row.protocol_version,
        "implementationVersion": (
            current.implementation_version
            if current is not None
            else (
                BUILTIN_IMPLEMENTATION_VERSION
                if row.definition_type == "builtin"
                else CUSTOM_IMPLEMENTATION_VERSION
            )
        ),
        "definitionSha256": row.definition_sha256,
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
    try:
        out["params"] = _loads_params(row.params_json)
    except JsonCorruptError as exc:
        out["params"] = None
        out["status"] = "data_corrupt"
        out["error"] = f"params_json corrupt: {exc}"
    if current is not None and row.definition_type == "custom_python":
        out["sourceCode"] = current.source_code
    return out


def _serialize_version(row: StrategyVersion, *, include_source: bool = True) -> dict:
    result = {
        "id": row.id,
        "strategyId": row.strategy_id,
        "version": row.version,
        "definitionType": row.definition_type,
        "builtinType": row.builtin_type,
        "category": row.category,
        "params": _loads_params(row.params_json),
        "definitionSha256": row.definition_sha256,
        "protocolVersion": row.protocol_version,
        "implementationVersion": row.implementation_version,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }
    if include_source and row.definition_type == "custom_python":
        result["sourceCode"] = row.source_code
    return result


def _version(
    session, user_id: str, strategy_id: str, version: int
) -> StrategyVersion | None:
    return session.execute(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.user_id == user_id,
            StrategyVersion.version == version,
        )
    ).scalar_one_or_none()


def _append_version(
    session,
    row: Strategy,
    *,
    params: dict[str, Any],
    source_code: str | None,
) -> StrategyVersion:
    version = StrategyVersion(
        id=str(uuid4()),
        strategy_id=row.id,
        user_id=row.user_id,
        version=row.current_version,
        definition_type=row.definition_type,
        builtin_type=row.builtin_type,
        category=row.category,
        params_json=_dump_params(params),
        source_code=source_code,
        definition_sha256=row.definition_sha256,
        protocol_version=row.protocol_version,
        implementation_version=(
            BUILTIN_IMPLEMENTATION_VERSION
            if row.definition_type == "builtin"
            else CUSTOM_IMPLEMENTATION_VERSION
        ),
    )
    session.add(version)
    return version


def _owned(
    session,
    user_id: str,
    strategy_id: str,
    *,
    for_update: bool = False,
) -> Strategy | None:
    statement = select(Strategy).where(
        Strategy.id == strategy_id,
        Strategy.user_id == user_id,
        Strategy.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    return session.execute(statement).scalar_one_or_none()


def list_strategies(
    user_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
    status: str | None = None,
    category: str | None = None,
    builtin_type: str | None = None,
    search: str | None = None,
    sort_by: str = "updatedAt",
    sort_order: str = "desc",
) -> dict:
    conditions = [
        Strategy.user_id == user_id,
        Strategy.deleted_at.is_(None),
    ]
    if status:
        conditions.append(Strategy.status == status)
    if category:
        conditions.append(Strategy.category == category)
    if builtin_type:
        conditions.append(Strategy.builtin_type == builtin_type)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Strategy.name.ilike(pattern),
                Strategy.description.ilike(pattern),
            )
        )

    sort_columns = {
        "name": Strategy.name,
        "createdAt": Strategy.created_at,
        "updatedAt": Strategy.updated_at,
        "status": Strategy.status,
    }
    sort_column = sort_columns.get(sort_by, Strategy.updated_at)
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()

    with SessionLocal() as session:
        total = session.execute(
            select(func.count()).select_from(Strategy).where(*conditions)
        ).scalar_one()
        rows = session.execute(
            select(Strategy)
            .where(*conditions)
            .order_by(ordering, Strategy.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return {"items": [_serialize(row) for row in rows], "total": total}


def get_strategy(user_id: str, strategy_id: str) -> dict | None:
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id)
        if row is None:
            return None
        current = _version(session, user_id, strategy_id, row.current_version)
        return _serialize(row, current)


def create_strategy(
    user_id: str,
    *,
    name: str,
    description: str,
    builtin_type: str | None,
    params: dict[str, Any],
    definition_type: str = "builtin",
    source_code: str | None = None,
) -> dict:
    category, stored_type, normalized, normalized_source, digest = (
        validate_definition(
            definition_type,
            builtin_type,
            params,
            source_code,
        )
    )
    row = Strategy(
        id=str(uuid4()),
        user_id=user_id,
        name=name.strip(),
        description=description or "",
        category=category,
        builtin_type=stored_type,
        definition_type=definition_type,
        current_version=1,
        protocol_version=PROTOCOL_VERSION,
        definition_sha256=digest,
        params_json=_dump_params(normalized),
        status="draft",
    )
    with SessionLocal() as session:
        session.add(row)
        _append_version(
            session,
            row,
            params=normalized,
            source_code=normalized_source,
        )
        session.commit()
        session.refresh(row)
        current = _version(session, user_id, row.id, row.current_version)
        return _serialize(row, current)


def update_strategy(
    user_id: str,
    strategy_id: str,
    changes: dict[str, Any],
) -> dict | None:
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id, for_update=True)
        if row is None:
            return None
        expected_version = changes.pop("expected_version", None)

        if "name" in changes and changes["name"] is not None:
            row.name = changes["name"].strip()
        if "description" in changes and changes["description"] is not None:
            row.description = changes["description"]

        definition_changed = bool(
            {"definition_type", "builtin_type", "params", "source_code"} & set(changes)
        )
        if definition_changed:
            if expected_version is None:
                raise ValueError("修改策略定义必须提供 expectedVersion")
            if expected_version != row.current_version:
                raise StrategyConflictError(
                    "策略定义已被并发更新，请刷新后重试"
                )
            new_definition_type = (
                changes.get("definition_type") or row.definition_type
            )
            changing_kind = new_definition_type != row.definition_type
            if "builtin_type" in changes:
                new_builtin_type = changes["builtin_type"]
            elif changing_kind:
                new_builtin_type = None
            else:
                new_builtin_type = (
                    None
                    if new_definition_type == "custom_python"
                    else row.builtin_type
                )
            if "params" in changes and changes["params"] is not None:
                new_params = changes["params"]
            elif changing_kind or (
                new_builtin_type is not None
                and new_builtin_type != row.builtin_type
            ):
                new_params = {}
            else:
                try:
                    new_params = _loads_params(row.params_json)
                except JsonCorruptError as exc:
                    raise ValueError(f"策略参数已损坏，请重新提交 params: {exc}") from exc
            if "source_code" in changes:
                new_source = changes["source_code"]
            elif not changing_kind and row.definition_type == "custom_python":
                current = _version(
                    session, user_id, strategy_id, row.current_version
                )
                new_source = current.source_code if current else None
            else:
                new_source = None
            category, stored_type, normalized, normalized_source, digest = (
                validate_definition(
                    new_definition_type,
                    new_builtin_type,
                    new_params,
                    new_source,
                )
            )
            if digest != row.definition_sha256:
                row.definition_type = new_definition_type
                row.builtin_type = stored_type
                row.category = category
                row.params_json = _dump_params(normalized)
                row.protocol_version = PROTOCOL_VERSION
                row.definition_sha256 = digest
                row.current_version += 1
                row.status = "draft"
                _append_version(
                    session,
                    row,
                    params=normalized,
                    source_code=normalized_source,
                )

        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if definition_changed:
                raise StrategyConflictError(
                    "策略定义已被并发更新，请刷新后重试"
                ) from exc
            raise
        session.refresh(row)
        current = _version(session, user_id, strategy_id, row.current_version)
        return _serialize(row, current)


def delete_strategy(user_id: str, strategy_id: str) -> bool:
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id, for_update=True)
        if row is None:
            return False
        row.status = "deleted"
        row.deleted_at = datetime.now(UTC)
        session.commit()
        return True


def set_status(user_id: str, strategy_id: str, status: str) -> dict | None:
    if status not in STRATEGY_STATUSES:
        raise ValueError("无效策略状态")
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id, for_update=True)
        if row is None:
            return None
        row.status = status
        session.commit()
        session.refresh(row)
        return _serialize(row)


def list_versions(user_id: str, strategy_id: str) -> list[dict] | None:
    with SessionLocal() as session:
        if _owned(session, user_id, strategy_id) is None:
            return None
        rows = session.execute(
            select(StrategyVersion)
            .where(
                StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.user_id == user_id,
            )
            .order_by(StrategyVersion.version.desc())
        ).scalars().all()
        return [_serialize_version(row, include_source=False) for row in rows]


def get_version(
    user_id: str, strategy_id: str, version: int
) -> dict | None:
    with SessionLocal() as session:
        if _owned(session, user_id, strategy_id) is None:
            return None
        row = _version(session, user_id, strategy_id, version)
        return _serialize_version(row) if row is not None else None


def run_version_signals(
    user_id: str,
    strategy_id: str,
    version: int,
    *,
    context: dict[str, Any],
    bars: dict[str, list[dict[str, Any]]],
) -> dict | None:
    with SessionLocal() as session:
        if _owned(session, user_id, strategy_id) is None:
            return None
        row = _version(session, user_id, strategy_id, version)
        if row is None:
            return None
        if row.protocol_version != PROTOCOL_VERSION:
            raise ValueError(
                f"不支持历史策略协议 {row.protocol_version}，需要对应版本执行器"
            )
        expected_implementation = (
            BUILTIN_IMPLEMENTATION_VERSION
            if row.definition_type == "builtin"
            else CUSTOM_IMPLEMENTATION_VERSION
        )
        if row.implementation_version != expected_implementation:
            raise ValueError(
                "策略实现版本与当前执行器不兼容，需要对应版本执行器"
            )
        params = _loads_params(row.params_json)
        definition = {
            "definition_type": row.definition_type,
            "builtin_type": (
                row.builtin_type if row.definition_type == "builtin" else None
            ),
            "params": params,
            "source_code": row.source_code,
        }
        digest = row.definition_sha256
        protocol_version = row.protocol_version
    from app.services.strategy_signals import generate_signals

    result = generate_signals(
        **definition,
        context=context,
        bars=bars,
    )
    return {
        "strategyId": strategy_id,
        "version": version,
        "definitionSha256": digest,
        "protocolVersion": protocol_version,
        "result": result,
    }


def duplicate_strategy(user_id: str, strategy_id: str) -> dict | None:
    with SessionLocal() as session:
        source = _owned(session, user_id, strategy_id)
        if source is None:
            return None
        source_version = _version(
            session, user_id, strategy_id, source.current_version
        )
        suffix = "（副本）"
        copied = Strategy(
            id=str(uuid4()),
            user_id=user_id,
            name=f"{source.name[: 128 - len(suffix)]}{suffix}",
            description=source.description,
            category=source.category,
            builtin_type=source.builtin_type,
            definition_type=source.definition_type,
            current_version=1,
            protocol_version=source.protocol_version,
            definition_sha256=source.definition_sha256,
            params_json=source.params_json,
            status="draft",
        )
        session.add(copied)
        _append_version(
            session,
            copied,
            params=_loads_params(source.params_json),
            source_code=source_version.source_code if source_version else None,
        )
        session.commit()
        session.refresh(copied)
        current = _version(session, user_id, copied.id, 1)
        return _serialize(copied, current)
