"""Persistent, encrypted verification-email delivery outbox."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.auth import VerificationEmailOutbox
from app.services.email_sender import send_verification_email

logger = logging.getLogger(__name__)
_scheduler = None


def _now() -> datetime:
    return datetime.now(UTC)


def encrypt_token(token: str) -> str:
    return Fernet(settings.auth_outbox_encryption_key.encode()).encrypt(token.encode()).decode()


def _decrypt_token(ciphertext: str) -> str:
    return Fernet(settings.auth_outbox_encryption_key.encode()).decrypt(
        ciphertext.encode()
    ).decode()


def requeue_failed_outbox(session: Session, token_hash: str, now: datetime) -> None:
    row = session.execute(
        select(VerificationEmailOutbox).where(
            VerificationEmailOutbox.token_hash == token_hash
        )
    ).scalar_one_or_none()
    if (
        row is not None
        and row.status == "failed"
        and row.attempts < settings.auth_outbox_max_attempts
    ):
        row.status = "pending"
        row.next_attempt = now


def deliver_due_verification_emails(*, now: datetime | None = None) -> int:
    delivery_time = now or _now()
    sent = 0
    with SessionLocal.begin() as session:
        statement = (
            select(VerificationEmailOutbox)
            .where(
                VerificationEmailOutbox.status.in_(("pending", "failed")),
                VerificationEmailOutbox.next_attempt <= delivery_time,
                VerificationEmailOutbox.attempts < settings.auth_outbox_max_attempts,
            )
            .order_by(VerificationEmailOutbox.next_attempt)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = session.execute(statement).scalars().all()
        for row in rows:
            row.attempts += 1
            row.updated_at = delivery_time
            try:
                token = _decrypt_token(row.encrypted_token)
                send_verification_email(row.recipient, token)
            except Exception as exc:  # noqa: BLE001
                row.status = "failed"
                row.last_error = type(exc).__name__[:128]
                delay = settings.auth_outbox_retry_base_seconds * (
                    2 ** (row.attempts - 1)
                )
                row.next_attempt = delivery_time + timedelta(seconds=delay)
                logger.warning(
                    "verification email delivery failed "
                    "(outbox_id=%s, attempt=%s, error_type=%s)",
                    row.id,
                    row.attempts,
                    type(exc).__name__,
                )
            else:
                row.status = "sent"
                row.last_error = None
                sent += 1
    return sent


def start_outbox_scheduler():
    global _scheduler
    if _scheduler is not None or not settings.enable_auth_outbox_scheduler:
        return _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        deliver_due_verification_emails,
        "interval",
        seconds=max(settings.auth_outbox_poll_seconds, 1),
        id="deliver_verification_email_outbox",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_outbox_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
