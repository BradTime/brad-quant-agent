"""Persisted built-in strategy CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.core.response import error, success
from app.models.user import User
from app.schemas.strategy import StrategyCreateRequest, StrategyUpdateRequest
from app.services import strategy

router = APIRouter()


@router.get("")
def list_strategies(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, alias="pageSize", ge=1, le=100),
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    builtin_type: str | None = Query(default=None, alias="builtinType"),
    sortBy: str = "updatedAt",
    sortOrder: str = "desc",
    search: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    return success(
        strategy.list_strategies(
            str(user.id),
            page=page,
            page_size=page_size,
            status=status,
            category=category,
            builtin_type=builtin_type,
            sort_by=sortBy,
            sort_order=sortOrder,
            search=search,
        )
    )


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str, user: User = Depends(get_current_user)):
    result = strategy.get_strategy(str(user.id), strategy_id)
    if result is None:
        return error("策略不存在", code=404, http_status=404)
    return success(result)


@router.post("")
def create_strategy(
    body: StrategyCreateRequest,
    user: User = Depends(get_current_user),
):
    try:
        result = strategy.create_strategy(
            str(user.id),
            name=body.name,
            description=body.description,
            builtin_type=body.builtin_type,
            params=body.params,
        )
    except ValueError as exc:
        return error(str(exc), code=400, http_status=400)
    return success(result)


@router.put("/{strategy_id}")
def update_strategy(
    strategy_id: str,
    body: StrategyUpdateRequest,
    user: User = Depends(get_current_user),
):
    try:
        result = strategy.update_strategy(
            str(user.id),
            strategy_id,
            body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        return error(str(exc), code=400, http_status=400)
    if result is None:
        return error("策略不存在", code=404, http_status=404)
    return success(result)


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str, user: User = Depends(get_current_user)):
    if not strategy.delete_strategy(str(user.id), strategy_id):
        return error("策略不存在", code=404, http_status=404)
    return success({"deleted": True})


@router.post("/{strategy_id}/enable")
def enable_strategy(strategy_id: str, user: User = Depends(get_current_user)):
    result = strategy.set_status(str(user.id), strategy_id, "active")
    if result is None:
        return error("策略不存在", code=404, http_status=404)
    return success(result)


@router.post("/{strategy_id}/disable")
def disable_strategy(strategy_id: str, user: User = Depends(get_current_user)):
    result = strategy.set_status(str(user.id), strategy_id, "disabled")
    if result is None:
        return error("策略不存在", code=404, http_status=404)
    return success(result)


@router.post("/{strategy_id}/duplicate")
def duplicate_strategy(strategy_id: str, user: User = Depends(get_current_user)):
    result = strategy.duplicate_strategy(str(user.id), strategy_id)
    if result is None:
        return error("策略不存在", code=404, http_status=404)
    return success(result)
