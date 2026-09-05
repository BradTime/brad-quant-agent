"""HttpOnly auth cookies (M20).

Cookie names are fixed so Next.js middleware can gate SSR routes without
decoding JWTs. Access/refresh JWTs themselves keep existing TTLs.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import settings
from app.core.security import REFRESH_TOKEN_EXPIRE_MINUTES

ACCESS_COOKIE = "qa_access"
REFRESH_COOKIE = "qa_refresh"


def _secure() -> bool:
    return bool(settings.is_production)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/",
        max_age=max(int(settings.access_token_expire_minutes), 1) * 60,
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/",
        max_age=max(int(REFRESH_TOKEN_EXPIRE_MINUTES), 1) * 60,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=ACCESS_COOKIE, path="/")
    response.delete_cookie(key=REFRESH_COOKIE, path="/")
