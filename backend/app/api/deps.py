"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.models.user import User
from app.services import auth as auth_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未认证")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = auth_service.get_user_by_id(str(payload.get("sub")))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user
