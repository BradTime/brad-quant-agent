"""Auth service: enumeration-safe registration, authentication, and tokens.

User data is scoped by a stable ``id`` (uuid4) so everything downstream can be
``user_id``-isolated (multi-user ready). Only successful login returns
``AuthResponse``; registration returns a generic accepted result without tokens.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.auth import EmailVerification, VerificationEmailOutbox
from app.models.user import User
from app.services.verification_outbox import encrypt_token, requeue_failed_outbox

AUTH_FAILURE_MESSAGE = "无法完成认证"
REGISTRATION_ACCEPTED_MESSAGE = "如果可以创建账户，注册请求已受理"
REGISTRATION_ACCEPTED = {
    "accepted": True,
    "message": REGISTRATION_ACCEPTED_MESSAGE,
}
def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
    }


def build_auth_response(user: User) -> dict:
    version = int(user.token_version or 0)
    return {
        "user": serialize_user(user),
        "token": security.create_access_token(user.id, version),
        "refreshToken": security.create_refresh_token(user.id, version),
    }


def register_user(email: str, password: str, name: str | None) -> dict:
    email = email.strip().lower()
    now = _now()
    with SessionLocal() as session:
        try:
            user = session.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
            if settings.auth_auto_verify_registration:
                if user is not None:
                    return REGISTRATION_ACCEPTED.copy()
                user = User(
                    id=str(uuid.uuid4()),
                    email=email,
                    name=(name or email.split("@")[0]),
                    password_hash=security.hash_password(password),
                    role="user",
                    email_verified_at=now,
                )
                session.add(user)
                session.commit()
                return REGISTRATION_ACCEPTED.copy()
            if user is not None:
                return REGISTRATION_ACCEPTED.copy()

            pending = session.execute(
                select(EmailVerification).where(
                    EmailVerification.email == email,
                    EmailVerification.consumed_at.is_(None),
                )
            ).scalar_one_or_none()
            if pending is not None and _aware(pending.expires_at) > now:
                requeue_failed_outbox(session, pending.token_hash, now)
                session.commit()
                return REGISTRATION_ACCEPTED.copy()
            # 过期 pending：删除旧 verification+outbox 再发新 token。
            # 不用“先 consumed 再 insert”——SQLite 部分唯一索引对未提交行
            # 可能仍挡住同 email 的活跃行。
            if pending is not None:
                old_hash = pending.token_hash
                session.execute(
                    delete(VerificationEmailOutbox).where(
                        VerificationEmailOutbox.token_hash == old_hash
                    )
                )
                session.execute(
                    delete(EmailVerification).where(
                        EmailVerification.token_hash == old_hash
                    )
                )
                session.flush()

            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            session.add(
                EmailVerification(
                    token_hash=token_hash,
                    email=email,
                    requested_name=name or email.split("@")[0],
                    expires_at=now
                    + timedelta(hours=settings.auth_verification_expire_hours),
                )
            )
            session.add(
                VerificationEmailOutbox(
                    token_hash=token_hash,
                    recipient=email,
                    encrypted_token=encrypt_token(raw_token),
                    status="pending",
                    attempts=0,
                    next_attempt=now,
                )
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            return REGISTRATION_ACCEPTED.copy()
    return REGISTRATION_ACCEPTED.copy()


def authenticate(email: str, password: str) -> dict:
    email = email.strip().lower()
    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        valid, needs_rehash = security.verify_password_constant(
            password,
            user.password_hash if user is not None else None,
        )
        if user is None or user.email_verified_at is None or not valid:
            raise ValueError(AUTH_FAILURE_MESSAGE)
        if needs_rehash:
            user.password_hash = security.hash_password(password)
            session.commit()
        return build_auth_response(user)


def verify_email_token(token: str, password: str, name: str) -> bool:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = _now()
    with SessionLocal.begin() as session:
        statement = select(EmailVerification).where(
            EmailVerification.token_hash == token_hash,
            EmailVerification.consumed_at.is_(None),
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        verification = session.execute(statement).scalar_one_or_none()
        if verification is None:
            return False
        # SQLite 读回的 expires_at 可能无 tz；Python 侧用 _aware 判过期。
        # UPDATE 以 token_hash + consumed_at 原子消费（synchronize_session=False
        # 避免 ORM 在 identity map 里做 naive/aware 比较炸掉）。
        if _aware(verification.expires_at) <= now:
            return False
        password_hash = security.hash_password(password)
        consumed = session.execute(
            update(EmailVerification)
            .where(
                EmailVerification.token_hash == token_hash,
                EmailVerification.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
            .returning(EmailVerification.email)
        ).scalar_one_or_none()
        if consumed is None:
            return False
        existing = session.execute(
            select(User).where(User.email == consumed)
        ).scalar_one_or_none()
        if existing is not None:
            return False
        session.add(
            User(
                id=str(uuid.uuid4()),
                email=consumed,
                name=name,
                password_hash=password_hash,
                role="user",
                email_verified_at=now,
            )
        )
        return True


def get_user_by_id(user_id: str) -> User | None:
    with SessionLocal() as session:
        return session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()


def user_matches_token_version(user_id: str, token_version: int | None) -> User | None:
    """令牌 tv 与用户当前 token_version 一致时返回用户，否则 None。"""
    if token_version is None:
        return None
    user = get_user_by_id(user_id)
    if user is None or int(user.token_version or 0) != int(token_version):
        return None
    return user


def revoke_user_tokens(user_id: str) -> bool:
    """递增 token_version，使既有 access/refresh JWT 全部失效。"""
    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.id == user_id).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            return False
        user.token_version = int(user.token_version or 0) + 1
        session.commit()
        return True
