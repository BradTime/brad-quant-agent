"""CRUD and validation for user-owned, catalog-backed strategies."""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select

from app.db.session import SessionLocal
from app.models.strategy import Strategy
from app.services.backtest_run import strategy_catalog

ALLOWED_BUILTIN_TYPES = frozenset({"dual_ma", "rsi", "boll", "momentum"})
STRATEGY_STATUSES = frozenset({"draft", "active", "disabled"})

_CATEGORY_BY_BUILTIN = {
    "dual_ma": "trend_following",
    "rsi": "mean_reversion",
    "boll": "mean_reversion",
    "momentum": "momentum",
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

    return _CATEGORY_BY_BUILTIN[builtin_type], normalized


def _loads_params(raw: str) -> dict[str, int | float]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _serialize(row: Strategy) -> dict:
    return {
        "id": row.id,
        "userId": row.user_id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "builtinType": row.builtin_type,
        "params": _loads_params(row.params_json),
        "status": row.status,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _owned(session, user_id: str, strategy_id: str) -> Strategy | None:
    return session.execute(
        select(Strategy).where(
            Strategy.id == strategy_id,
            Strategy.user_id == user_id,
        )
    ).scalar_one_or_none()


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
    conditions = [Strategy.user_id == user_id]
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
        return _serialize(row) if row is not None else None


def create_strategy(
    user_id: str,
    *,
    name: str,
    description: str,
    builtin_type: str,
    params: dict[str, Any],
) -> dict:
    category, normalized = validate_params(builtin_type, params)
    row = Strategy(
        id=str(uuid4()),
        user_id=user_id,
        name=name.strip(),
        description=description or "",
        category=category,
        builtin_type=builtin_type,
        params_json=json.dumps(normalized, ensure_ascii=False, allow_nan=False),
        status="draft",
    )
    with SessionLocal() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize(row)


def update_strategy(
    user_id: str,
    strategy_id: str,
    changes: dict[str, Any],
) -> dict | None:
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id)
        if row is None:
            return None

        if "name" in changes and changes["name"] is not None:
            row.name = changes["name"].strip()
        if "description" in changes and changes["description"] is not None:
            row.description = changes["description"]

        definition_changed = "builtin_type" in changes or "params" in changes
        if definition_changed:
            new_type = changes.get("builtin_type") or row.builtin_type
            if "params" in changes and changes["params"] is not None:
                new_params = changes["params"]
            elif new_type != row.builtin_type:
                new_params = {}
            else:
                new_params = _loads_params(row.params_json)
            category, normalized = validate_params(new_type, new_params)
            row.builtin_type = new_type
            row.category = category
            row.params_json = json.dumps(
                normalized,
                ensure_ascii=False,
                allow_nan=False,
            )

        session.commit()
        session.refresh(row)
        return _serialize(row)


def delete_strategy(user_id: str, strategy_id: str) -> bool:
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def set_status(user_id: str, strategy_id: str, status: str) -> dict | None:
    if status not in STRATEGY_STATUSES:
        raise ValueError("无效策略状态")
    with SessionLocal() as session:
        row = _owned(session, user_id, strategy_id)
        if row is None:
            return None
        row.status = status
        session.commit()
        session.refresh(row)
        return _serialize(row)


def duplicate_strategy(user_id: str, strategy_id: str) -> dict | None:
    with SessionLocal() as session:
        source = _owned(session, user_id, strategy_id)
        if source is None:
            return None
        suffix = "（副本）"
        copied = Strategy(
            id=str(uuid4()),
            user_id=user_id,
            name=f"{source.name[: 128 - len(suffix)]}{suffix}",
            description=source.description,
            category=source.category,
            builtin_type=source.builtin_type,
            params_json=source.params_json,
            status="draft",
        )
        session.add(copied)
        session.commit()
        session.refresh(copied)
        return _serialize(copied)
