"""Backtest endpoints (Phase 4 M3)：同步跑回测 + 落库 + 历史回看 + 内置策略目录。

回测为秒级计算，采用同步 POST /run（非 SSE）：跑完即落库并返回完整结果。
受 ``ai_cost_gate("backtest")`` 每用户每日配额保护。``/strategies`` 声明在 ``/{id}`` 之前，
避免被路径变量误匹配。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.ai.orchestrator import run_completion_stream
from app.ai.prompts import BACKTEST_REVIEW_PROMPT
from app.api.deps import get_current_user
from app.backtest.base import BacktestConfig
from app.core.cors import apply_cors_headers
from app.core.response import error, success
from app.models.user import User
from app.schemas.backtest import GridSearchRequest, RunBacktestRequest
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


@router.post("/grid")
def grid(req: GridSearchRequest, user: User = Depends(get_current_user)):
    """参数网格寻优：对参数笛卡尔积逐组回测并排名（只加载一次行情）。走回测配额闸。"""
    codes = [c for c in (req.codes or []) if c and c.strip()]
    if not codes:
        return error("请至少选择一个标的（如 600000.SH）", code=400, http_status=400)
    if not req.paramGrid or not any(req.paramGrid.values()):
        return error("请至少提供一个参数的候选值网格", code=400, http_status=400)
    blocked = rate_limit.ai_cost_gate(str(user.id), "backtest")
    if blocked:
        return error(blocked, code=429, http_status=429)
    cfg = BacktestConfig(
        strategy_type=req.strategyType, params={}, codes=codes,
        start=req.start, end=req.end, initial_capital=req.initialCapital, slippage=req.slippage,
        frequency=req.frequency,
    )
    return success(backtest_run.grid_search(cfg, req.paramGrid, req.sortBy))


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


@router.post("/{backtest_id}/review")
def review(
    backtest_id: str, request: Request, user: User = Depends(get_current_user)
) -> StreamingResponse:
    """AI 回测诊断（单轮合成，走成本闸；只喂真实回测结果）。SSE 流式 delta/[DONE]。"""
    user_id = str(user.id)
    text = backtest_run.build_review_input(user_id, backtest_id)
    blocked = rate_limit.ai_cost_gate(user_id, "chat") if text else None

    def event_stream():
        if text is None:
            yield f"data: {json.dumps({'error': '回测结果不存在'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        if blocked:
            yield f"data: {json.dumps({'error': blocked}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        try:
            for piece in run_completion_stream(BACKTEST_REVIEW_PROMPT, text):
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    apply_cors_headers(request.headers.get("origin"), response)
    return response
