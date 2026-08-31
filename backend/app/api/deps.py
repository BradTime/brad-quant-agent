"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth_cookies import ACCESS_COOKIE
from app.core.security import decode_token, token_version_of
from app.models.user import User
from app.services import auth as auth_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    token: str | None = None
    if credentials is not None:
        token = credentials.credentials
    else:
        raw = request.cookies.get(ACCESS_COOKIE)
        if raw:
            token = raw
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未认证")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = auth_service.user_matches_token_version(
        str(payload.get("sub")),
        token_version_of(payload),
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌已失效")
    return user
