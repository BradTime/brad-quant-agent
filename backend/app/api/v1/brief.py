"""盘前早报端点（Phase 2）。

- ``GET  /api/v1/brief/latest``      最新一份早报（当前用户个性化）
- ``GET  /api/v1/brief``             历史列表（不含正文）
- ``GET  /api/v1/brief/{id}``        某份早报详情
- ``POST /api/v1/brief/generate``    现在生成（SSE 流式，结束落库）
- ``GET  /api/v1/brief/global/latest`` 系统级全局早报（调度器每日生成）
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.cors import apply_cors_headers
from app.core.response import success
from app.models.user import User
from app.services import brief

router = APIRouter()


@router.get("/latest")
def latest(user: User = Depends(get_current_user)) -> dict:
    return success(brief.get_latest(str(user.id)))


@router.get("/global/latest")
def global_latest(user: User = Depends(get_current_user)) -> dict:
    return success(brief.get_latest(None))


@router.get("")
def history(limit: int = 20, user: User = Depends(get_current_user)) -> dict:
    return success(brief.list_briefs(str(user.id), limit))


@router.get("/{brief_id}")
def detail(brief_id: str, user: User = Depends(get_current_user)) -> dict:
    return success(brief.get_brief(brief_id, str(user.id)))


@router.post("/generate")
def generate(
    request: Request,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    user_id = str(user.id)

    def event_stream():
        try:
            # stream_generate 产出事件 dict：{"step":...}（多智能体进度）或 {"delta":...}（正文）
            for event in brief.stream_generate(user_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    response = StreamingResponse(event_stream(), media_type="text/event-stream")
    apply_cors_headers(request.headers.get("origin"), response)
    return response
