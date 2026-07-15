"""Unified API response helpers.

Keeps the same envelope the existing Next.js frontend expects:
``{ code, message, data, timestamp }``.
"""

import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.cors import apply_cors_headers


def _now_ms() -> int:
    return int(time.time() * 1000)


def success(data: Any = None, message: str = "success", code: int = 200) -> dict:
    return {"code": code, "message": message, "data": data, "timestamp": _now_ms()}


def error(
    message: str,
    code: int | str = 500,
    http_status: int = 500,
    request: Request | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=http_status,
        content={"code": code, "message": message, "data": None, "timestamp": _now_ms()},
    )
    if request is not None:
        apply_cors_headers(request.headers.get("origin"), response)
    return response
