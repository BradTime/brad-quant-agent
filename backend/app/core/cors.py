"""CORS origin checks shared by middleware and error responses."""

from __future__ import annotations

import re

from app.core.config import settings

_CORS_LAN_REGEX = (
    r"https?://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)


def cors_lan_regex() -> str:
    return _CORS_LAN_REGEX


def is_allowed_origin(origin: str) -> bool:
    if origin in settings.cors_origin_list:
        return True
    if settings.cors_allow_private_lan:
        return bool(re.fullmatch(_CORS_LAN_REGEX, origin))
    return False


def apply_cors_headers(origin: str | None, response) -> None:
    if not origin or not is_allowed_origin(origin):
        return
    response.headers["access-control-allow-origin"] = origin
    response.headers["access-control-allow-credentials"] = "true"
    response.headers.setdefault("vary", "Origin")
