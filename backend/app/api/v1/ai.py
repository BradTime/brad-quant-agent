"""AI 看盘问答端点（SSE 流式，需认证）。

请求体：``{"messages":[{"role":"user","content":"..."}]}``
响应：``text/event-stream``，每帧 ``data: {"delta": "..."}``，结束 ``data: [DONE]``。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.ai.orchestrator import run_chat_stream
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.ai import ChatRequest

router = APIRouter()


@router.post("/chat")
def chat(body: ChatRequest, user: User = Depends(get_current_user)) -> StreamingResponse:
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    def event_stream():
        try:
            for piece in run_chat_stream(messages):
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
