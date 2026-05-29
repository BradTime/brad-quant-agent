"""Password hashing (bcrypt) and JWT signing/verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# pbkdf2_sha256：无 bcrypt 的 72 字节密码限制，纯 hashlib 实现、跨 Python 版本稳定。
# 保留 bcrypt 仅用于校验历史哈希（新密码统一用 pbkdf2_sha256）。
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")

_REFRESH_TOKEN_MINUTES = 60 * 24 * 7  # 7 天


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except ValueError:
        return False


def _create_token(subject: str, expires_minutes: int, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> str:
    return _create_token(subject, settings.access_token_expire_minutes, "access")


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, _REFRESH_TOKEN_MINUTES, "refresh")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
