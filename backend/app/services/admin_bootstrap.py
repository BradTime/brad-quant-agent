"""Safe, auditable promotion of verified users to administrator."""

from __future__ import annotations

from uuid import uuid4

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import inspect, select, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.admin import AdminPrivilegeAudit
from app.models.user import User

EXPECTED_ALEMBIC_HEAD = "20260902_0013"


class AdminBootstrapError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _normalize_email(value: str) -> str:
    try:
        return validate_email(
            value.strip(),
            check_deliverability=False,
        ).normalized.lower()
    except EmailNotValidError as exc:
        raise AdminBootstrapError("INVALID_EMAIL", "邮箱格式无效") from exc


def _mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    visible = local[:1]
    return f"{visible}{'*' * max(len(local) - 1, 2)}@{domain}"


def _assert_environment(expected: str) -> str:
    actual = settings.app_env.strip().lower()
    if expected.strip().lower() != actual:
        raise AdminBootstrapError(
            "ENVIRONMENT_MISMATCH",
            "目标环境与当前 APP_ENV 不一致",
        )
    return actual


def _assert_migration_head(db) -> None:
    if not inspect(db.get_bind()).has_table("alembic_version"):
        raise AdminBootstrapError("MIGRATION_REQUIRED", "数据库尚未由 Alembic 管理")
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != EXPECTED_ALEMBIC_HEAD:
        raise AdminBootstrapError(
            "MIGRATION_REQUIRED",
            "数据库 migration 不是当前 head",
        )


def inspect_account(email: str) -> dict:
    normalized = _normalize_email(email)
    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.email == normalized)
        ).scalar_one_or_none()
        if user is None:
            raise AdminBootstrapError("USER_NOT_FOUND", "账户不存在")
        return {
            "targetUserId": user.id,
            "maskedEmail": _mask_email(user.email),
            "verified": user.email_verified_at is not None,
            "role": user.role,
        }


def promote_existing(
    *,
    email: str,
    expected_user_id: str,
    expected_environment: str,
    apply: bool,
) -> dict:
    normalized = _normalize_email(email)
    environment = _assert_environment(expected_environment)
    with SessionLocal.begin() as db:
        _assert_migration_head(db)
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('admin-bootstrap-promotion'))"
                )
            )
        user = db.execute(
            select(User).where(User.email == normalized).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise AdminBootstrapError("USER_NOT_FOUND", "账户不存在")
        if user.id != expected_user_id:
            raise AdminBootstrapError(
                "USER_ID_MISMATCH",
                "账户 UUID 与确认值不一致",
            )
        if user.email_verified_at is None:
            raise AdminBootstrapError("USER_UNVERIFIED", "账户尚未完成邮箱验证")

        prior_role = user.role
        changed = prior_role != "admin"
        result = {
            "ok": True,
            "action": "promote-existing",
            "applied": apply,
            "changed": changed if apply else False,
            "wouldChange": changed,
            "targetUserId": user.id,
            "maskedEmail": _mask_email(user.email),
            "currentRole": prior_role,
            "proposedRole": "admin",
            "environment": environment,
        }
        if not apply:
            return result
        if changed:
            user.role = "admin"
            user.token_version = int(user.token_version or 0) + 1
        db.add(
            AdminPrivilegeAudit(
                id=str(uuid4()),
                action="promote-existing",
                target_user_id=user.id,
                target_user_id_snapshot=user.id,
                prior_role=prior_role,
                new_role="admin",
                changed=changed,
                environment=environment,
                actor_type="local_cli",
            )
        )
        return result


def list_admins() -> list[dict]:
    with SessionLocal() as db:
        rows = db.execute(
            select(User).where(User.role == "admin").order_by(User.id)
        ).scalars().all()
        return [
            {
                "targetUserId": row.id,
                "maskedEmail": _mask_email(row.email),
                "verified": row.email_verified_at is not None,
            }
            for row in rows
        ]
