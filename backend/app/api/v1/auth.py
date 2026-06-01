"""Auth endpoints: register / login / logout / refresh / me.

Business failures (duplicate email, bad credentials) return the unified error
envelope so the frontend can display ``message``; 401 on protected routes uses
the standard status so the client's interceptor can react.
"""

from __future__ import annotations

from fastapi import Depends

from app.api.deps import get_current_user
from app.core.response import error, success
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest
from app.services import auth as auth_service

from fastapi import APIRouter

router = APIRouter()


@router.post("/register")
def register(body: RegisterRequest):
    try:
        data = auth_service.register_user(body.email, body.password, body.name)
    except ValueError as exc:
        return error(str(exc), code=10001, http_status=400)
    return success(data, message="注册成功")


@router.post("/login")
def login(body: LoginRequest):
    try:
        data = auth_service.authenticate(body.email, body.password)
    except ValueError as exc:
        return error(str(exc), code=10002, http_status=400)
    return success(data, message="登录成功")


@router.post("/logout")
def logout():
    return success(None, message="已登出")


@router.post("/refresh")
def refresh(body: RefreshRequest):
    payload = decode_token(body.refreshToken)
    if not payload or payload.get("type") != "refresh":
        return error("refresh token 无效或已过期", code=10003, http_status=401)
    subject = str(payload.get("sub"))
    # 校验用户仍存在（账号被删/禁用后，旧 refresh token 不应继续换新令牌）
    if auth_service.get_user_by_id(subject) is None:
        return error("用户不存在或已失效", code=10003, http_status=401)
    return success(
        {"token": create_access_token(subject), "refreshToken": create_refresh_token(subject)}
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success(auth_service.serialize_user(user))
