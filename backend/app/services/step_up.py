"""TOTP enrollment and one-time purpose-bound step-up grants."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core import security
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.room import (
    StepUpGrant,
    StepUpThrottle,
    TotpRecoveryCode,
    UserTotpFactor,
)
from app.models.user import User

PURPOSES = {
    "change_decision_mode",
    "delete_account",
    "override_decision",
    "release_kill_switch",
    "reset_totp",
    "submit_broker_simulation",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _cipher() -> Fernet:
    return Fernet(settings.auth_outbox_encryption_key.encode())


def _encrypt(secret: str) -> str:
    return _cipher().encrypt(secret.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("TOTP 密钥不可解密") from exc


def _code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(
        key, struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    value = (
        int.from_bytes(digest[offset : offset + 4], "big")
        & 0x7FFFFFFF
    )
    return f"{value % 1_000_000:06d}"


def _matching_counter(
    secret: str,
    candidate: str,
    *,
    now: datetime,
    last_counter: int | None,
) -> int | None:
    if len(candidate) != 6 or not candidate.isdigit():
        return None
    current = int(now.timestamp()) // 30
    for counter in range(current - 1, current + 2):
        if counter <= (last_counter if last_counter is not None else -1):
            continue
        if hmac.compare_digest(_code(secret, counter), candidate):
            return counter
    return None


def _throttle(session, user_id: str) -> StepUpThrottle:
    insert = (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert
    )
    session.execute(
        insert(StepUpThrottle)
        .values(user_id=user_id, failed_attempts=0)
        .on_conflict_do_nothing(
            index_elements=[StepUpThrottle.user_id]
        )
    )
    return session.execute(
        select(StepUpThrottle)
        .where(StepUpThrottle.user_id == user_id)
        .with_for_update()
    ).scalar_one()


def _check_lock(row: StepUpThrottle, now: datetime) -> None:
    if row.locked_until and _aware(row.locked_until) > now:
        raise ValueError("二次验证已临时锁定")


def _failure(row: StepUpThrottle, now: datetime) -> None:
    row.failed_attempts += 1
    if row.failed_attempts >= 5:
        row.locked_until = now + timedelta(minutes=15)
        row.failed_attempts = 0


def _success(row: StepUpThrottle) -> None:
    row.failed_attempts = 0
    row.locked_until = None


def _recovery_hash(code: str) -> str:
    normalized = code.replace("-", "").strip().upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def status(user_id: str) -> dict:
    with SessionLocal() as session:
        row = session.get(UserTotpFactor, user_id)
        return {
            "enabled": bool(row and row.enabled_at),
            "pending": bool(row and not row.enabled_at),
        }


def enroll(user_id: str, password: str) -> dict:
    now = _now()
    result = None
    failed = False
    with SessionLocal.begin() as session:
        user = session.execute(
            select(User).where(User.id == user_id).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        throttle = _throttle(session, user_id)
        _check_lock(throttle, now)
        valid, _ = security.verify_password_constant(
            password, user.password_hash
        )
        if not valid:
            _failure(throttle, now)
            failed = True
        else:
            row = session.get(UserTotpFactor, user_id)
            if row is not None and row.enabled_at is not None:
                raise ValueError("TOTP 已启用，不允许无二次验证重置")
            secret = (
                base64.b32encode(secrets.token_bytes(20))
                .decode()
                .rstrip("=")
            )
            if row is None:
                row = UserTotpFactor(
                    user_id=user_id,
                    secret_ciphertext=_encrypt(secret),
                )
                session.add(row)
            else:
                row.secret_ciphertext = _encrypt(secret)
                row.last_counter = None
            session.execute(
                delete(TotpRecoveryCode).where(
                    TotpRecoveryCode.user_id == user_id
                )
            )
            recovery_codes = []
            for _ in range(10):
                raw = secrets.token_hex(8).upper()
                display = "-".join(
                    raw[index : index + 4]
                    for index in range(0, len(raw), 4)
                )
                recovery_codes.append(display)
                session.add(
                    TotpRecoveryCode(
                        id=str(uuid4()),
                        user_id=user_id,
                        code_hash=_recovery_hash(display),
                    )
                )
            _success(throttle)
            issuer = quote(settings.app_name, safe="")
            account = quote(user.email, safe="")
            result = {
                "secret": secret,
                "otpauthUri": (
                    f"otpauth://totp/{issuer}:{account}"
                    f"?secret={secret}&issuer={issuer}&algorithm=SHA1"
                    "&digits=6&period=30"
                ),
                "expiresNotice": "确认前再次 enroll 会替换此密钥",
                "recoveryCodes": recovery_codes,
                "createdAt": now.isoformat(),
            }
    if failed or result is None:
        raise ValueError("密码或动态验证码错误")
    return result


def confirm(user_id: str, code: str) -> dict:
    now = _now()
    result = None
    failed = False
    with SessionLocal.begin() as session:
        user = session.execute(
            select(User).where(User.id == user_id).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        throttle = _throttle(session, user_id)
        _check_lock(throttle, now)
        row = session.execute(
            select(UserTotpFactor)
            .where(UserTotpFactor.user_id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or row.enabled_at is not None:
            raise ValueError("没有待确认的 TOTP")
        counter = _matching_counter(
            _decrypt(row.secret_ciphertext),
            code,
            now=now,
            last_counter=row.last_counter,
        )
        if counter is None:
            _failure(throttle, now)
            failed = True
        else:
            row.enabled_at = now
            row.last_counter = counter
            _success(throttle)
            result = {"enabled": True, "enabledAt": now.isoformat()}
    if failed or result is None:
        raise ValueError("密码或动态验证码错误")
    return result


def create_grant(
    user_id: str,
    *,
    password: str,
    code: str | None,
    recovery_code: str | None = None,
    purpose: str,
) -> dict:
    if purpose not in PURPOSES:
        raise ValueError("二次验证用途无效")
    if bool(code) == bool(recovery_code):
        raise ValueError("必须且只能提交动态验证码或恢复码")
    if recovery_code and purpose not in {"reset_totp", "delete_account"}:
        raise ValueError("恢复码仅允许重置 TOTP 或删除账户")
    now = _now()
    result = None
    failed = False
    with SessionLocal.begin() as session:
        user = session.execute(
            select(User).where(User.id == user_id).with_for_update()
        ).scalar_one_or_none()
        throttle = _throttle(session, user_id)
        _check_lock(throttle, now)
        row = session.execute(
            select(UserTotpFactor)
            .where(UserTotpFactor.user_id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if user is None or row is None or row.enabled_at is None:
            raise ValueError("必须先启用 TOTP")
        valid_password, _ = security.verify_password_constant(
            password, user.password_hash
        )
        counter = None
        recovery = None
        if code:
            counter = _matching_counter(
                _decrypt(row.secret_ciphertext),
                code,
                now=now,
                last_counter=row.last_counter,
            )
            second_factor_valid = counter is not None
        else:
            recovery = session.execute(
                select(TotpRecoveryCode)
                .where(
                    TotpRecoveryCode.user_id == user_id,
                    TotpRecoveryCode.code_hash
                    == _recovery_hash(recovery_code or ""),
                    TotpRecoveryCode.used_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            second_factor_valid = recovery is not None
        if not valid_password or not second_factor_valid:
            _failure(throttle, now)
            failed = True
        else:
            if counter is not None:
                row.last_counter = counter
            if recovery is not None:
                recovery.used_at = now
            _success(throttle)
            grant_id = str(uuid4())
            token = security.create_step_up_token(
                user_id,
                purpose,
                grant_id,
                int(user.token_version or 0),
            )
            session.add(
                StepUpGrant(
                    id=grant_id,
                    user_id=user_id,
                    purpose=purpose,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=now + timedelta(minutes=5),
                )
            )
            result = {
                "token": token,
                "purpose": purpose,
                "expiresAt": (now + timedelta(minutes=5)).isoformat(),
            }
    if failed or result is None:
        raise ValueError("密码或动态验证码错误")
    return result


def reset_factor(user: User, *, token: str) -> dict:
    with SessionLocal.begin() as session:
        locked_user = session.execute(
            select(User)
            .where(User.id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        if locked_user is None:
            raise ValueError("用户不存在")
        consume(
            session,
            user=locked_user,
            token=token,
            purpose="reset_totp",
        )
        session.execute(
            delete(UserTotpFactor).where(
                UserTotpFactor.user_id == str(user.id)
            )
        )
        session.execute(
            delete(TotpRecoveryCode).where(
                TotpRecoveryCode.user_id == str(user.id)
            )
        )
        session.execute(
            delete(StepUpGrant).where(
                StepUpGrant.user_id == str(user.id)
            )
        )
        locked_user.token_version = int(
            locked_user.token_version or 0
        ) + 1
    return {
        "enabled": False,
        "reset": True,
        "tokensRevoked": True,
    }


def consume(
    session,
    *,
    user: User,
    token: str,
    purpose: str,
) -> None:
    payload = security.decode_token(token)
    if (
        not payload
        or payload.get("type") != "step_up"
        or payload.get("sub") != str(user.id)
        or payload.get("purpose") != purpose
        or payload.get("tv") != int(user.token_version or 0)
        or not isinstance(payload.get("jti"), str)
    ):
        raise ValueError("二次验证凭证无效")
    now = _now()
    row = session.execute(
        select(StepUpGrant)
        .where(
            StepUpGrant.id == payload["jti"],
            StepUpGrant.user_id == str(user.id),
            StepUpGrant.purpose == purpose,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if (
        row is None
        or row.consumed_at is not None
        or _aware(row.expires_at) <= now
        or not hmac.compare_digest(
            row.token_hash,
            hashlib.sha256(token.encode()).hexdigest(),
        )
    ):
        raise ValueError("二次验证凭证已使用或过期")
    row.consumed_at = now
