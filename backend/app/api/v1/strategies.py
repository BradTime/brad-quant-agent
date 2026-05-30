"""Strategy management endpoints (Phase 4 placeholder).

The legacy frontend strategy pages expect these routes. Phase 1 focuses on
market watch + AI Q&A; full strategy CRUD and backtest land in Phase 4.
Until then, list returns an empty page and mutating routes respond with 501.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.response import error, success

router = APIRouter()


@router.get("")
def list_strategies(
    page: int = 1,
    pageSize: int = 10,
    status: str | None = None,
    strategy_type: str | None = Query(default=None, alias="type"),
    sortBy: str = "updatedAt",
    sortOrder: str = "desc",
    search: str | None = None,
) -> dict:
    # Query params accepted for API compatibility; filtering applies once Phase 4 ships.
    _ = (page, pageSize, status, strategy_type, sortBy, sortOrder, search)
    return success({"items": [], "total": 0})


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error("策略不存在", code=404, http_status=404)


@router.post("")
def create_strategy() -> dict:
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )


@router.put("/{strategy_id}")
def update_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )


@router.post("/{strategy_id}/enable")
def enable_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )


@router.post("/{strategy_id}/disable")
def disable_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )


@router.post("/{strategy_id}/duplicate")
def duplicate_strategy(strategy_id: str) -> dict:
    _ = strategy_id
    return error(
        "策略管理功能将在量化研究阶段（Phase 4）开放",
        code=501,
        http_status=501,
    )
