from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.db.base import Base
from app.models.auth import AuthThrottle, EmailVerification, VerificationEmailOutbox
from app.models.user import User
from app.services import auth, verification_outbox


def _pending_token(sessions) -> str:
    """解密当前未消费 verification 对应的 outbox token（避免同秒多行误取旧 token）。"""
    with sessions() as session:
        verification = session.scalar(
            select(EmailVerification)
            .where(EmailVerification.consumed_at.is_(None))
            .order_by(EmailVerification.created_at.desc())
        )
        assert verification is not None
        outbox = session.scalar(
            select(VerificationEmailOutbox).where(
                VerificationEmailOutbox.token_hash == verification.token_hash
            )
        )
        assert outbox is not None
        return Fernet(auth.settings.auth_outbox_encryption_key.encode()).decrypt(
            outbox.encrypted_token.encode()
        ).decode()


@pytest.fixture
def verification_env(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AuthThrottle.__table__,
            EmailVerification.__table__,
            VerificationEmailOutbox.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    sent: list[tuple[str, str]] = []
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(verification_outbox, "SessionLocal", sessions)
    monkeypatch.setattr(auth.settings, "auth_auto_verify_registration", False)
    monkeypatch.setattr(auth, "_now", lambda: now)
    monkeypatch.setattr(verification_outbox, "_now", lambda: now)
    monkeypatch.setattr(
        verification_outbox,
        "send_verification_email",
        lambda email, token: sent.append((email, token)),
    )
    try:
        yield sessions, sent, now
    finally:
        engine.dispose()


def test_pending_user_cannot_login_then_verifies_once(verification_env) -> None:
    sessions, sent, now = verification_env
    auth.register_user("pending@example.com", "ValidPass1!", "Pending")
    token = _pending_token(sessions)
    assert sent == []

    with pytest.raises(ValueError, match=auth.AUTH_FAILURE_MESSAGE):
        auth.authenticate("pending@example.com", "ValidPass1!")
    with sessions() as session:
        user = session.scalar(select(User).where(User.email == "pending@example.com"))
        verification = session.scalar(select(EmailVerification))
        assert user is None
        assert verification is not None
        assert verification.email == "pending@example.com"
        assert verification.requested_name == "Pending"
        assert verification.token_hash != token
        assert verification.expires_at.replace(tzinfo=UTC) == now + timedelta(hours=24)

    assert auth.verify_email_token(token, "OwnerPass2@", "Email Owner") is True
    assert auth.authenticate("pending@example.com", "OwnerPass2@")["user"]["email"] == (
        "pending@example.com"
    )
    assert auth.verify_email_token(token, "AnotherPass3#", "Attacker") is False


def test_expired_token_fails_and_reregistration_refreshes_it(verification_env) -> None:
    sessions, sent, now = verification_env
    auth.register_user("pending@example.com", "ValidPass1!", "Pending")
    old_token = _pending_token(sessions)
    with sessions.begin() as session:
        verification = session.scalar(select(EmailVerification))
        assert verification is not None
        verification.expires_at = now - timedelta(seconds=1)

    assert auth.verify_email_token(old_token, "OwnerPass2@", "Owner") is False
    auth.register_user("pending@example.com", "ValidPass1!", "Ignored")
    new_token = _pending_token(sessions)
    assert new_token != old_token
    assert auth.verify_email_token(old_token, "OwnerPass2@", "Owner") is False
    assert auth.verify_email_token(new_token, "OwnerPass2@", "Owner") is True


def test_token_only_activates_its_linked_user(verification_env) -> None:
    sessions, sent, _ = verification_env
    auth.register_user("a@example.com", "ValidPass1!", "A")
    token_a = _pending_token(sessions)
    auth.register_user("b@example.com", "ValidPass1!", "B")

    assert auth.verify_email_token(token_a, "OwnerPass2@", "Owner A") is True
    with sessions() as session:
        users = {
            user.email: user.email_verified_at
            for user in session.scalars(select(User)).all()
        }
    assert users["a@example.com"] is not None
    assert "b@example.com" not in users


def test_repeated_pending_registration_keeps_token_and_cannot_preseed_password(
    verification_env,
) -> None:
    sessions, sent, _ = verification_env
    auth.register_user("victim@example.com", "AttackerPass1!", "Attacker")
    token = _pending_token(sessions)
    auth.register_user("victim@example.com", "VictimDraft2@", "Victim Draft")

    assert sent == []
    with sessions() as session:
        assert session.scalar(select(User).where(User.email == "victim@example.com")) is None
        assert session.scalar(select(EmailVerification)).token_hash
        assert session.query(VerificationEmailOutbox).count() == 1

    assert auth.verify_email_token(token, "VictimFinal3#", "Victim Owner") is True
    assert auth.authenticate("victim@example.com", "VictimFinal3#")
    with pytest.raises(ValueError, match=auth.AUTH_FAILURE_MESSAGE):
        auth.authenticate("victim@example.com", "AttackerPass1!")
    with sessions() as session:
        user = session.scalar(select(User).where(User.email == "victim@example.com"))
        assert user is not None and user.name == "Victim Owner"


def test_auto_verify_creates_active_user_without_sending(
    verification_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, sent, _ = verification_env
    monkeypatch.setattr(auth.settings, "auth_auto_verify_registration", True)
    auth.register_user("dev@example.com", "ValidPass1!", "Dev")
    assert sent == []
    assert auth.authenticate("dev@example.com", "ValidPass1!")
    with sessions() as session:
        assert session.scalar(select(User).where(User.email == "dev@example.com")).email_verified_at


def test_invalid_or_expired_token_does_not_hash_password(
    verification_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, _, now = verification_env
    monkeypatch.setattr(
        security,
        "hash_password",
        lambda _password: pytest.fail("invalid token must not hash"),
    )
    assert auth.verify_email_token("x" * 43, "ValidPass1!", "Owner") is False

    auth.register_user("expired@example.com", "ValidPass1!", "Expired")
    token = _pending_token(sessions)
    with sessions.begin() as session:
        verification = session.scalar(
            select(EmailVerification).where(EmailVerification.email == "expired@example.com")
        )
        assert verification is not None
        verification.expires_at = now - timedelta(seconds=1)
    assert auth.verify_email_token(token, "ValidPass1!", "Owner") is False


def test_outbox_failure_retries_and_recovers_without_rotating_token(
    verification_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, sent, now = verification_env
    auth.register_user("retry@example.com", "ValidPass1!", "Retry")
    token = _pending_token(sessions)
    assert sent == []

    def fail_smtp(_email: str, _token: str) -> None:
        raise RuntimeError("smtp unavailable secret-token-must-not-persist")

    monkeypatch.setattr(verification_outbox, "send_verification_email", fail_smtp)
    assert verification_outbox.deliver_due_verification_emails(now=now) == 0
    with sessions() as session:
        row = session.scalar(select(VerificationEmailOutbox))
        assert row is not None
        assert row.status == "failed"
        assert row.attempts == 1
        assert "secret-token" not in (row.last_error or "")
        retry_at = row.next_attempt

    auth.register_user("retry@example.com", "AnotherPass2@", "Ignored")
    assert _pending_token(sessions) == token
    with sessions() as session:
        assert session.query(VerificationEmailOutbox).count() == 1

    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(
        verification_outbox,
        "send_verification_email",
        lambda email, raw: delivered.append((email, raw)),
    )
    assert verification_outbox.deliver_due_verification_emails(
        now=retry_at.replace(tzinfo=UTC)
    ) == 1
    assert delivered == [("retry@example.com", token)]
    with sessions() as session:
        row = session.scalar(select(VerificationEmailOutbox))
        assert row is not None and row.status == "sent" and row.attempts == 2


def test_concurrent_verification_creates_exactly_one_user(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'verify-race.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            AuthThrottle.__table__,
            EmailVerification.__table__,
            VerificationEmailOutbox.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    sent: list[str] = []
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(verification_outbox, "SessionLocal", sessions)
    monkeypatch.setattr(auth.settings, "auth_auto_verify_registration", False)
    monkeypatch.setattr(
        verification_outbox,
        "send_verification_email",
        lambda _email, token: sent.append(token),
    )
    auth.register_user("race@example.com", "DraftPass1!", "Draft")
    token = _pending_token(sessions)
    assert sent == []
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _index: auth.verify_email_token(
                        token, "FinalPass2@", "Race Owner"
                    ),
                    range(2),
                )
            )
        assert sorted(results) == [False, True]
        with sessions() as session:
            assert session.query(User).filter_by(email="race@example.com").count() == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["missing", "pbkdf2", "bcrypt"])
def test_login_always_performs_one_pbkdf2_and_one_bcrypt_check(
    verification_env,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    sessions, _, now = verification_env
    password = "old pass"
    if kind != "missing":
        password_hash = (
            security.hash_password(password)
            if kind == "pbkdf2"
            else security.bcrypt.hashpw(password.encode(), security.bcrypt.gensalt()).decode()
        )
        with sessions.begin() as session:
            session.add(
                User(
                    id=f"{kind}-user",
                    email=f"{kind}@example.com",
                    name=kind,
                    password_hash=password_hash,
                    role="user",
                    email_verified_at=now,
                )
            )

    calls = {"pbkdf2": 0, "bcrypt": 0}
    real_pbkdf2 = security._verify_pbkdf2
    real_bcrypt = security._verify_bcrypt

    def count_pbkdf2(candidate: str, encoded: str) -> bool:
        calls["pbkdf2"] += 1
        return real_pbkdf2(candidate, encoded)

    def count_bcrypt(candidate: str, encoded: str) -> bool:
        calls["bcrypt"] += 1
        return real_bcrypt(candidate, encoded)

    monkeypatch.setattr(security, "_verify_pbkdf2", count_pbkdf2)
    monkeypatch.setattr(security, "_verify_bcrypt", count_bcrypt)
    email = f"{kind}@example.com"
    if kind == "missing":
        with pytest.raises(ValueError, match=auth.AUTH_FAILURE_MESSAGE):
            auth.authenticate(email, password)
    else:
        assert auth.authenticate(email, password)
    assert calls == {"pbkdf2": 1, "bcrypt": 1}

    if kind == "bcrypt":
        with sessions() as session:
            user = session.scalar(select(User).where(User.email == email))
            assert user is not None
            assert user.password_hash.startswith("$pbkdf2-sha256$")
