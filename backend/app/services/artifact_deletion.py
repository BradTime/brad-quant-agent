"""Persistent post-commit deletion outbox for user training artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.room import UserArtifactDeletion
from app.services import training_data


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    session,
    *,
    user_id: str,
    paths: list[str],
) -> list[str]:
    insert = (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert
    )
    cipher = Fernet(settings.auth_outbox_encryption_key.encode())
    ids = []
    for path in sorted(set(paths)):
        path_hash = hashlib.sha256(
            f"{user_id}\0{path}".encode()
        ).hexdigest()
        deletion_id = str(uuid4())
        result = session.execute(
            insert(UserArtifactDeletion)
            .values(
                id=deletion_id,
                user_id_snapshot=user_id,
                path_ciphertext=cipher.encrypt(path.encode()).decode(),
                path_sha256=path_hash,
                status="pending",
                attempts=0,
                next_attempt_at=_now(),
            )
            .on_conflict_do_nothing(
                index_elements=[UserArtifactDeletion.path_sha256]
            )
        )
        if result.rowcount:
            ids.append(deletion_id)
    return ids


def process(deletion_id: str) -> bool:
    token = str(uuid4())
    now = _now()
    with SessionLocal.begin() as session:
        row = session.execute(
            select(UserArtifactDeletion)
            .where(UserArtifactDeletion.id == deletion_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None or row.status == "completed":
            return True
        started = row.claim_started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (
            row.claim_token
            and started is not None
            and started > now - timedelta(minutes=5)
        ):
            return False
        row.claim_token = token
        row.claim_started_at = now
        row.status = "processing"
        ciphertext = row.path_ciphertext
    try:
        path = (
            Fernet(settings.auth_outbox_encryption_key.encode())
            .decrypt(ciphertext.encode())
            .decode()
        )
        succeeded = training_data.remove_artifact_after_commit(path)
    except (InvalidToken, UnicodeDecodeError, OSError, ValueError):
        succeeded = False
    with SessionLocal.begin() as session:
        row = session.execute(
            select(UserArtifactDeletion)
            .where(
                UserArtifactDeletion.id == deletion_id,
                UserArtifactDeletion.claim_token == token,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return False
        row.attempts += 1
        row.claim_token = None
        row.claim_started_at = None
        if succeeded:
            row.status = "completed"
            row.completed_at = _now()
            row.path_ciphertext = ""
        else:
            row.status = "pending"
            row.next_attempt_at = _now() + timedelta(
                seconds=min(3600, 60 * (2 ** (row.attempts - 1)))
            )
    return succeeded


def process_due(*, limit: int = 100) -> int:
    now = _now()
    stale = now - timedelta(minutes=5)
    with SessionLocal() as session:
        ids = session.execute(
            select(UserArtifactDeletion.id)
            .where(
                UserArtifactDeletion.status.in_(["pending", "processing"]),
                UserArtifactDeletion.next_attempt_at <= now,
                (
                    UserArtifactDeletion.claim_token.is_(None)
                    | (UserArtifactDeletion.claim_started_at <= stale)
                ),
            )
            .order_by(UserArtifactDeletion.created_at)
            .limit(limit)
        ).scalars().all()
    for deletion_id in ids:
        process(deletion_id)
    return len(ids)
