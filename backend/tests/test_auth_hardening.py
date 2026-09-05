from __future__ import annotations

import base64
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.schemas.auth import LoginRequest, RegisterRequest

STRONG_PASSWORD = "ValidPass1!"
# 必须与 config._DEFAULT_OUTBOX_KEY 不同，否则生产校验会拒绝
_PROD_OUTBOX_KEY = "ZJN11AF-N3EN-1YNbmjiPQPLUSORpzWElFTdmo_f9sU="


def test_auth_schemas_normalize_and_forbid_extra_fields() -> None:
    request = RegisterRequest(
        email="  USER@Example.COM ",
        password=STRONG_PASSWORD,
        name="  Alice  ",
    )
    assert str(request.email) == "user@example.com"
    assert request.name == "Alice"

    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password=STRONG_PASSWORD,
            name="Alice",
            unexpected=True,
        )


@pytest.mark.parametrize(
    "password",
    [
        "Short1!",
        "lowercase1!",
        "UPPERCASE1!",
        "NoDigits!!",
        "NoSpecial11",
        "Has space1!",
        "Has\nControl1!",
        "A1!" + "x" * 126,
    ],
)
def test_registration_rejects_weak_or_out_of_bounds_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=password, name="Alice")


@pytest.mark.parametrize("name", ["", " ", "x" * 65, "Alice\nAdmin"])
def test_registration_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=STRONG_PASSWORD, name=name)


def test_login_enforces_only_shared_length_and_character_boundaries() -> None:
    request = LoginRequest(email=" USER@example.com ", password="old pass")
    assert str(request.email) == "user@example.com"
    assert request.password == "old pass"
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="")
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="x" * 257)
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="old\x00pass")


@pytest.mark.parametrize("password", ["ÄBCDEFGH1!", "abcdefghé1!", "Ａbcdefgh1!"])
def test_registration_requires_ascii_character_classes(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=password, name="Alice")


@pytest.mark.parametrize(
    ("secret", "algorithm"),
    [
        ("x" * 32, "HS256"),
        ("change-me-in-production-change-me", "HS256"),
        ("correct horse battery staple 123!", "HS512"),
        ("too-short-but-varied-123!", "HS256"),
        ("ab" * 32, "HS256"),
        ("0" * 64, "HS256"),
        (base64.urlsafe_b64encode(b"repeat" * 6).decode().rstrip("="), "HS256"),
    ],
)
def test_production_rejects_weak_secret_or_non_whitelisted_algorithm(
    secret: str, algorithm: str
) -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret=secret, jwt_algorithm=algorithm)


def test_production_accepts_strong_hs256_secret() -> None:
    secrets = [
        "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("="),
    ]
    for secret in secrets:
        settings = Settings(
            app_env="production",
            jwt_secret=secret,
            jwt_algorithm="HS256",
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            frontend_url="https://example.com",
            auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
        )
        assert settings.jwt_algorithm == "HS256"


def test_production_requires_smtp_and_disables_auto_verification() -> None:
    secret = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    with pytest.raises(ValidationError):
        Settings(app_env="production", jwt_secret=secret)
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret=secret,
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            frontend_url="https://example.com",
            auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
            auth_auto_verify_registration=True,
        )
    # 默认 outbox key 不得用于生产
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret=secret,
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            frontend_url="https://example.com",
            auth_outbox_encryption_key="vB38N4l1nnNNX-fEgdhxgLk37KFuWKBAhcTW1XZOrfc=",
            auth_auto_verify_registration=False,
        )
    configured = Settings(
        app_env="production",
        jwt_secret=secret,
        smtp_host="smtp.example.com",
        smtp_user="mailer",
        smtp_password="secret",
        smtp_from="noreply@example.com",
        frontend_url="https://example.com",
        auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
        auth_auto_verify_registration=False,
    )
    assert configured.auth_auto_verify_registration is False
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret=secret,
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            frontend_url="http://example.com",
            auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
            auth_auto_verify_registration=False,
        )
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret=secret,
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            smtp_starttls=False,
            frontend_url="https://example.com",
            auth_outbox_encryption_key=_PROD_OUTBOX_KEY,
            auth_auto_verify_registration=False,
        )
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            jwt_secret=secret,
            smtp_host="smtp.example.com",
            smtp_user="mailer",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            frontend_url="https://example.com",
            auth_outbox_encryption_key="invalid",
            auth_auto_verify_registration=False,
        )


def test_nonproduction_defaults_to_auto_verification() -> None:
    assert Settings(app_env="test").auth_auto_verify_registration is True


def test_client_ip_uses_trusted_cidrs_and_rightmost_untrusted_hop() -> None:
    from app.core.client_ip import resolve_client_ip

    assert (
        resolve_client_ip(
            peer_host="10.0.0.8",
            forwarded_for="192.0.2.99, 198.51.100.9, 10.0.0.7",
            trusted_proxies=(),
        )
        == "10.0.0.8"
    )
    assert (
        resolve_client_ip(
            peer_host="10.0.0.8",
            forwarded_for="192.0.2.99, 198.51.100.9, 10.0.0.7",
            trusted_proxies=("10.0.0.0/24",),
        )
        == "198.51.100.9"
    )


def test_client_ip_handles_ipv6_and_rejects_invalid_xff_conservatively() -> None:
    from app.core.client_ip import resolve_client_ip

    assert (
        resolve_client_ip(
            peer_host="2001:db8:ffff::2",
            forwarded_for="2001:db8:1::9, 2001:db8:ffff::1",
            trusted_proxies=("2001:db8:ffff::/48",),
        )
        == "2001:db8:1::9"
    )
    assert (
        resolve_client_ip(
            peer_host="10.0.0.8",
            forwarded_for="198.51.100.9, definitely-invalid",
            trusted_proxies=("10.0.0.0/24",),
        )
        == "10.0.0.8"
    )


@pytest.fixture
def throttle_session():
    from app.models.auth import AuthThrottle

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[AuthThrottle.__table__])
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def test_throttle_locks_at_limit_resets_window_and_clears_account(
    throttle_session,
) -> None:
    from app.services.auth_throttle import AuthThrottleStore

    store = AuthThrottleStore(throttle_session)
    start = datetime(2026, 7, 17, 12, tzinfo=UTC)
    bucket = store.login_email_bucket("USER@example.com")

    for attempt in range(1, 5):
        assert store.record_failure(bucket, now=start, limit=5, window=900, lock=900) is False
        assert store.failures(bucket, now=start) == attempt
    assert store.record_failure(bucket, now=start, limit=5, window=900, lock=900) is True
    assert store.is_locked(bucket, now=start + timedelta(seconds=899))
    assert not store.is_locked(bucket, now=start + timedelta(seconds=901))

    store.record_failure(bucket, now=start + timedelta(seconds=901), limit=5, window=900, lock=900)
    assert store.failures(bucket, now=start + timedelta(seconds=901)) == 1
    store.clear(bucket)
    assert store.failures(bucket, now=start + timedelta(seconds=901)) == 0


def test_account_and_ip_buckets_are_isolated(throttle_session) -> None:
    from app.services.auth_throttle import AuthThrottleStore

    store = AuthThrottleStore(throttle_session)
    now = datetime(2026, 7, 17, 12, tzinfo=UTC)
    account = store.login_email_bucket("user@example.com")
    other_account = store.login_email_bucket("other@example.com")
    ip = store.login_ip_bucket("198.51.100.9")

    store.record_failure(account, now=now, limit=5, window=900, lock=900)
    assert store.failures(account, now=now) == 1
    assert store.failures(other_account, now=now) == 0
    assert store.failures(ip, now=now) == 0


def test_postgres_throttle_updates_are_atomic_across_processes() -> None:
    from app.core.config import settings
    from app.models.auth import AuthThrottle

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        try:
            with engine.connect() as connection:
                if "auth_throttles" not in inspect(connection).get_table_names():
                    pytest.skip("auth_throttles migration has not been applied")
        except SQLAlchemyError as exc:
            pytest.skip(f"PostgreSQL unavailable: {exc}")

        bucket = f"test:process:{uuid4().hex}"
        code = (
            "from datetime import UTC, datetime;"
            "from app.db.session import SessionLocal;"
            "from app.services.auth_throttle import AuthThrottleStore;"
            f"AuthThrottleStore(SessionLocal).record_failure({bucket!r},"
            "now=datetime(2026,7,17,12,tzinfo=UTC),limit=100,window=900,lock=900)"
        )
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", code],
                env={**os.environ, "DATABASE_URL": settings.database_url},
            )
            for _ in range(8)
        ]
        assert [process.wait(timeout=30) for process in processes] == [0] * 8
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with session_factory() as session:
            row = session.get(AuthThrottle, bucket)
            assert row is not None
            assert row.failures == 8
            session.execute(delete(AuthThrottle).where(AuthThrottle.bucket == bucket))
            session.commit()
    finally:
        engine.dispose()
