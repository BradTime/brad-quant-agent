"""Backtest endpoints (Phase 4 M3)：同步跑回测 + 落库 + 历史回看 + 内置策略目录。

回测为秒级计算，采用同步 POST /run（非 SSE）：跑完即落库并返回完整结果。
受 ``ai_cost_gate("backtest")`` 每用户每日配额保护。``/strategies`` 声明在 ``/{id}`` 之前，
避免被路径变量误匹配。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.response import error, success
from app.models.user import User
from app.schemas.backtest import RunBacktestRequest
from app.services import backtest_run, rate_limit

router = APIRouter()


@router.get("/strategies")
def list_strategy_catalog() -> dict:
    """内置策略目录（type / 名称 / 说明 / 参数 schema），供前端选择与渲染参数表单。"""
    return success({"items": backtest_run.strategy_catalog()})


@router.post("/run")
def run_backtest_endpoint(req: RunBacktestRequest, user: User = Depends(get_current_user)):
    codes = [c for c in (req.codes or []) if c and c.strip()]
    if not codes:
        return error("请至少选择一个标的（如 600000.SH）", code=400, http_status=400)
    blocked = rate_limit.ai_cost_gate(str(user.id), "backtest")
    if blocked:
        return error(blocked, code=429, http_status=429)
    return success(backtest_run.run_and_save(str(user.id), req))


@router.get("")
def list_backtests(user: User = Depends(get_current_user)) -> dict:
    items = backtest_run.list_runs(str(user.id))
    return success({"items": items, "total": len(items)})


@router.get("/{backtest_id}")
def get_backtest(backtest_id: str, user: User = Depends(get_current_user)):
    result = backtest_run.get_run(str(user.id), backtest_id)
    if result is None:
        return error("回测结果不存在", code=404, http_status=404)
    return success(result)


@router.get("/{backtest_id}/metrics")
def get_metrics(backtest_id: str, user: User = Depends(get_current_user)):
    result = backtest_run.get_run(str(user.id), backtest_id)
    if result is None:
        return error("回测结果不存在", code=404, http_status=404)
    return success(result.get("metrics") or {})
