"""Database-backed, multi-worker-safe authentication throttles."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auth import AuthThrottle


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class AuthThrottleStore:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    @staticmethod
    def login_email_bucket(email: str) -> str:
        return f"login:email:{email.strip().lower()}"

    @staticmethod
    def login_ip_bucket(ip: str) -> str:
        return f"login:ip:{ip}"

    @staticmethod
    def register_ip_bucket(ip: str) -> str:
        return f"register:ip:{ip}"

    @staticmethod
    def verify_ip_bucket(ip: str) -> str:
        return f"verify:ip:{ip}"

    @staticmethod
    def _advisory_key(bucket: str) -> int:
        return int.from_bytes(hashlib.sha256(bucket.encode()).digest()[:8], "big", signed=True)

    def _lock(self, session: Session, bucket: str) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": self._advisory_key(bucket)},
            )

    def _row(self, session: Session, bucket: str) -> AuthThrottle | None:
        statement = select(AuthThrottle).where(AuthThrottle.bucket == bucket)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        return session.execute(statement).scalar_one_or_none()

    def is_locked(self, bucket: str, *, now: datetime) -> bool:
        with self._session_factory() as session:
            row = session.get(AuthThrottle, bucket)
            locked_until = _aware(row.locked_until) if row else None
            return bool(locked_until and locked_until > now)

    def failures(self, bucket: str, *, now: datetime) -> int:
        with self._session_factory() as session:
            row = session.get(AuthThrottle, bucket)
            if row is None:
                return 0
            return row.failures

    def record_failure(
        self,
        bucket: str,
        *,
        now: datetime,
        limit: int,
        window: int,
        lock: int,
    ) -> bool:
        with self._session_factory.begin() as session:
            self._lock(session, bucket)
            row = self._row(session, bucket)
            if row is None:
                row = AuthThrottle(bucket=bucket, failures=0, window_start=now)
                session.add(row)
                session.flush()

            window_start = _aware(row.window_start)
            locked_until = _aware(row.locked_until)
            if now >= window_start + timedelta(seconds=window):
                row.failures = 0
                row.window_start = now
                row.locked_until = None
                locked_until = None
            if locked_until and locked_until > now:
                return True

            row.failures += 1
            row.updated_at = now
            if row.failures >= limit:
                row.locked_until = now + timedelta(seconds=lock)
                return True
            return False

    def clear(self, bucket: str) -> None:
        with self._session_factory.begin() as session:
            self._lock(session, bucket)
            session.execute(delete(AuthThrottle).where(AuthThrottle.bucket == bucket))


def utc_now() -> datetime:
    return datetime.now(UTC)
