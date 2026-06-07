"""模拟交易端点（Phase 3）。

- ``GET    /api/v1/sim/account``        账户概览（现金/市值/总资产/盈亏）
- ``GET    /api/v1/sim/positions``      当前持仓
- ``GET    /api/v1/sim/orders``         委托记录
- ``GET    /api/v1/sim/trades``         成交记录
- ``POST   /api/v1/sim/orders``         下单（撮合：市价即时/限价可成交即成交，否则挂单）
- ``DELETE /api/v1/sim/orders/{id}``    撤销挂单
- ``POST   /api/v1/sim/review``         AI 账户复盘（SSE 流式，走成本闸）
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.ai.orchestrator import run_completion_stream
from app.ai.prompts import SIM_REVIEW_PROMPT
from app.api.deps import get_current_user
from app.core.cors import apply_cors_headers
from app.core.response import success
from app.models.user import User
from app.schemas.trading import OrderRequest
from app.services import rate_limit, trading

router = APIRouter()


@router.get("/account")
def account(user: User = Depends(get_current_user)) -> dict:
    return success(trading.get_account(str(user.id)))


@router.get("/positions")
def positions(user: User = Depends(get_current_user)) -> dict:
    return success(trading.get_positions(str(user.id)))


@router.get("/orders")
def orders(limit: int = 50, user: User = Depends(get_current_user)) -> dict:
    return success(trading.list_orders(str(user.id), limit))


@router.get("/trades")
def trades(limit: int = 50, user: User = Depends(get_current_user)) -> dict:
    return success(trading.list_trades(str(user.id), limit))


@router.post("/orders")
def place(body: OrderRequest, user: User = Depends(get_current_user)) -> dict:
    try:
        order = trading.place_order(
            str(user.id), body.code, body.side, body.type, body.price, body.qty
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(order)


@router.delete("/orders/{order_id}")
def cancel(order_id: str, user: User = Depends(get_current_user)) -> dict:
    try:
        res = trading.cancel_order(str(user.id), order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(res)


@router.post("/review")
def review(request: Request, user: User = Depends(get_current_user)) -> StreamingResponse:
    """AI 账户复盘（单轮合成，走成本闸；只喂真实账户数据）。"""
    user_id = str(user.id)
    blocked = rate_limit.ai_cost_gate(user_id, "chat")

    def event_stream():
        if blocked:
            yield f"data: {json.dumps({'error': blocked}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        try:
            text = trading.build_review_input(user_id)
            for piece in run_completion_stream(SIM_REVIEW_PROMPT, text):
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    apply_cors_headers(request.headers.get("origin"), response)
    return response
