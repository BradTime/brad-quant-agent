"""Backtest endpoints (Phase 4 placeholder).

The legacy frontend references these routes; the real backtest engine
(backtrader/qlib, T+1/复权/滑点/印花税, 策略 API 对齐 RQAlpha/JoinQuant) lands in
Phase 4. Until then, reads return empty/404 and mutating routes respond with 501
(instead of 404) so API consumers get a clear "not yet available" signal.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.response import error, success

router = APIRouter()

_PHASE4_MSG = "回测引擎将在量化研究阶段（Phase 4）开放"


@router.get("")
def list_backtests(page: int = 1, pageSize: int = 10) -> dict:
    _ = (page, pageSize)
    return success({"items": [], "total": 0})


@router.post("/run")
def run_backtest() -> dict:
    return error(_PHASE4_MSG, code=501, http_status=501)


@router.get("/{backtest_id}")
def get_backtest(backtest_id: str) -> dict:
    _ = backtest_id
    return error("回测结果不存在", code=404, http_status=404)


@router.get("/{backtest_id}/metrics")
def get_metrics(backtest_id: str) -> dict:
    _ = backtest_id
    return error(_PHASE4_MSG, code=501, http_status=501)


@router.get("/{backtest_id}/report")
def get_report(backtest_id: str) -> dict:
    _ = backtest_id
    return error(_PHASE4_MSG, code=501, http_status=501)


@router.post("/{backtest_id}/export")
def export_report(backtest_id: str) -> dict:
    _ = backtest_id
    return error(_PHASE4_MSG, code=501, http_status=501)
