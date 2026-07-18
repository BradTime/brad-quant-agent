"""Auth endpoints: register / login / logout / refresh / me.

Valid registration requests always return the same accepted response and never
issue tokens, preventing email enumeration. Bad credentials use one message;
401 on protected routes keeps the standard status for the client interceptor.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.api.deps import get_current_user
from app.core.client_ip import resolve_client_ip
from app.core.config import settings
from app.core.response import error, success
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    token_version_of,
)
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailRequest,
)
from app.services import auth as auth_service
from app.services.auth_throttle import AuthThrottleStore, utc_now
from app.services.verification_outbox import deliver_due_verification_emails

router = APIRouter()
_THROTTLED_MESSAGE = "请求过于频繁，请稍后再试"


def _client_ip(request: Request) -> str:
    return resolve_client_ip(
        peer_host=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        trusted_proxies=settings.auth_trusted_proxy_list,
    )


@router.post("/register", status_code=202)
def register(body: RegisterRequest, request: Request, background_tasks: BackgroundTasks):
    store = AuthThrottleStore(SessionLocal)
    bucket = store.register_ip_bucket(_client_ip(request))
    now = utc_now()
    if store.is_locked(bucket, now=now) or store.record_failure(
        bucket,
        now=now,
        limit=settings.auth_register_limit,
        window=settings.auth_register_window_seconds,
        lock=settings.auth_register_window_seconds,
    ):
        return error(_THROTTLED_MESSAGE, code=429, http_status=429, request=request)
    try:
        data = auth_service.register_user(str(body.email), body.password, body.name)
    except ValueError:
        return error(
            auth_service.AUTH_FAILURE_MESSAGE,
            code=10001,
            http_status=400,
            request=request,
        )
    background_tasks.add_task(deliver_due_verification_emails)
    return success(data, message=auth_service.REGISTRATION_ACCEPTED_MESSAGE)


@router.post("/login")
def login(body: LoginRequest, request: Request):
    store = AuthThrottleStore(SessionLocal)
    now = utc_now()
    ip_bucket = store.login_ip_bucket(_client_ip(request))
    account_bucket = store.login_email_bucket(str(body.email))
    if store.is_locked(ip_bucket, now=now) or store.is_locked(account_bucket, now=now):
        return error(_THROTTLED_MESSAGE, code=429, http_status=429, request=request)
    try:
        data = auth_service.authenticate(str(body.email), body.password)
    except ValueError:
        ip_locked = store.record_failure(
            ip_bucket,
            now=now,
            limit=settings.auth_login_limit,
            window=settings.auth_login_window_seconds,
            lock=settings.auth_login_lock_seconds,
        )
        account_locked = store.record_failure(
            account_bucket,
            now=now,
            limit=settings.auth_login_limit,
            window=settings.auth_login_window_seconds,
            lock=settings.auth_login_lock_seconds,
        )
        if ip_locked or account_locked:
            return error(_THROTTLED_MESSAGE, code=429, http_status=429, request=request)
        return error(
            auth_service.AUTH_FAILURE_MESSAGE,
            code=10002,
            http_status=400,
            request=request,
        )
    store.clear(account_bucket)
    return success(data, message="登录成功")


@router.post("/verify")
def verify_email(body: VerifyEmailRequest, request: Request):
    store = AuthThrottleStore(SessionLocal)
    now = utc_now()
    bucket = store.verify_ip_bucket(_client_ip(request))
    if store.is_locked(bucket, now=now):
        return error(_THROTTLED_MESSAGE, code=429, http_status=429, request=request)
    if not auth_service.verify_email_token(body.token, body.password, body.name):
        locked = store.record_failure(
            bucket,
            now=now,
            limit=settings.auth_verify_limit,
            window=settings.auth_verify_window_seconds,
            lock=settings.auth_verify_lock_seconds,
        )
        if locked:
            return error(_THROTTLED_MESSAGE, code=429, http_status=429, request=request)
        return error("验证链接无效或已过期", code=10004, http_status=400, request=request)
    store.clear(bucket)
    return success({"verified": True}, message="邮箱验证成功")


@router.post("/logout")
def logout(user: User = Depends(get_current_user)):
    auth_service.revoke_user_tokens(user.id)
    return success(None, message="已登出")


@router.post("/refresh")
def refresh(body: RefreshRequest):
    """Refresh 族轮换：消费当前 refresh 并递增 token_version，旧 refresh 立即失效。"""
    payload = decode_token(body.refreshToken)
    if not payload or payload.get("type") != "refresh":
        return error("refresh token 无效或已过期", code=10003, http_status=401)
    subject = str(payload.get("sub"))
    expected = token_version_of(payload)
    if expected is None:
        return error("refresh token 无效或已过期", code=10003, http_status=401)
    user = auth_service.rotate_refresh_tokens(subject, expected)
    if user is None:
        return error("用户不存在或令牌已失效", code=10003, http_status=401)
    version = int(user.token_version or 0)
    return success(
        {
            "token": create_access_token(subject, version),
            "refreshToken": create_refresh_token(subject, version),
        }
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success(auth_service.serialize_user(user))
