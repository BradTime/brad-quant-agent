from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_api
from app.core.security import hash_password
from app.db.base import Base
from app.main import app
from app.models.auth import AuthThrottle, EmailVerification, VerificationEmailOutbox
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services import auth as auth_service
from app.services import verification_outbox
from app.services.auth_throttle import AuthThrottleStore


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch):
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
    clock = {"now": datetime(2026, 7, 17, 12, tzinfo=UTC)}
    monkeypatch.setattr(auth_service, "SessionLocal", sessions)
    monkeypatch.setattr(auth_api, "SessionLocal", sessions)
    monkeypatch.setattr(verification_outbox, "SessionLocal", sessions)
    monkeypatch.setattr(auth_api, "utc_now", lambda: clock["now"])
    auth_service.register_user("user@example.com", "ValidPass1!", "Alice")
    try:
        yield TestClient(app), sessions, clock
    finally:
        engine.dispose()


def _login(client: TestClient, email: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"x-forwarded-for": "203.0.113.7"},
    )


def test_login_bruteforce_lock_is_uniform_and_success_resets_account(auth_client) -> None:
    client, sessions, clock = auth_client
    for _ in range(4):
        response = _login(client, "USER@example.com", "WrongPass1!")
        assert response.status_code == 400
        assert response.json()["message"] == auth_service.AUTH_FAILURE_MESSAGE

    response = _login(client, "user@example.com", "WrongPass1!")
    assert response.status_code == 429
    assert response.json()["message"] == "请求过于频繁，请稍后再试"

    clock["now"] += timedelta(seconds=901)
    response = _login(client, "user@example.com", "ValidPass1!")
    assert response.status_code == 200
    store = AuthThrottleStore(sessions)
    assert store.failures(store.login_email_bucket("user@example.com"), now=clock["now"]) == 0


def test_invalid_registration_uses_400_envelope(auth_client) -> None:
    client, _, _ = auth_client
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "weak", "name": " "},
    )
    assert response.status_code == 400
    assert response.json()["message"] == "请求参数无效"
    assert response.json()["data"] is None


def test_registration_is_enumeration_safe_and_never_issues_tokens(auth_client) -> None:
    client, sessions, _ = auth_client
    payload = {
        "email": "new@example.com",
        "password": "ValidPass1!",
        "name": "New User",
    }
    created = client.post("/api/v1/auth/register", json=payload)
    existing = client.post(
        "/api/v1/auth/register",
        json={**payload, "email": "user@example.com"},
    )

    assert created.status_code == existing.status_code == 202
    assert created.json()["data"] == existing.json()["data"] == {
        "accepted": True,
        "message": "如果可以创建账户，注册请求已受理",
    }
    assert "token" not in created.text
    with sessions() as session:
        assert session.query(User).filter_by(email="new@example.com").count() == 1
        assert session.query(User).filter_by(email="user@example.com").count() == 1


def test_login_accepts_legacy_eight_character_password_with_space(auth_client) -> None:
    client, sessions, _ = auth_client
    with sessions.begin() as session:
        session.add(
            User(
                id="legacy-user",
                email="legacy@example.com",
                name="Legacy",
                password_hash=hash_password("old pass"),
                role="user",
                email_verified_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
    response = _login(client, "legacy@example.com", "old pass")
    assert response.status_code == 200


def test_verify_endpoint_activates_pending_registration(
    auth_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = auth_client
    sent: list[str] = []
    monkeypatch.setattr(auth_service.settings, "auth_auto_verify_registration", False)
    monkeypatch.setattr(
        verification_outbox,
        "send_verification_email",
        lambda _email, token: sent.append(token),
    )
    payload = {
        "email": "verify@example.com",
        "password": "ValidPass1!",
        "name": "Verify",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    assert _login(client, payload["email"], payload["password"]).status_code == 400
    verification_body = {
        "token": sent[-1],
        "password": "FinalPass2@",
        "name": "Verified Owner",
    }
    verified = client.post("/api/v1/auth/verify", json=verification_body)
    assert verified.status_code == 200
    assert verified.json()["data"] == {"verified": True}
    assert _login(client, payload["email"], "FinalPass2@").status_code == 200
    assert client.post("/api/v1/auth/verify", json=verification_body).status_code == 400


def test_verify_invalid_tokens_are_ip_throttled_without_hashing(
    auth_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = auth_client
    monkeypatch.setattr(
        auth_service.security,
        "hash_password",
        lambda _password: pytest.fail("invalid token must not hash"),
    )
    body = {"token": "x" * 43, "password": "ValidPass1!", "name": "Owner"}
    for _ in range(9):
        assert client.post("/api/v1/auth/verify", json=body).status_code == 400
    response = client.post("/api/v1/auth/verify", json=body)
    assert response.status_code == 429
    assert response.json()["message"] == "请求过于频繁，请稍后再试"


def test_registration_response_path_never_calls_smtp(
    auth_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _ = auth_client
    queued: list[object] = []
    background = SimpleNamespace(
        add_task=lambda function, *_args, **_kwargs: queued.append(function)
    )
    monkeypatch.setattr(auth_service.settings, "auth_auto_verify_registration", False)
    response = auth_api.register(
        RegisterRequest(
            email="async@example.com",
            password="ValidPass1!",
            name="Async",
        ),
        SimpleNamespace(client=SimpleNamespace(host="testclient"), headers={}),
        background,
    )
    assert response["data"]["accepted"] is True
    assert queued


def test_untrusted_forwarded_for_does_not_split_ip_bucket(auth_client) -> None:
    client, sessions, clock = auth_client
    for index in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": f"missing{index}@example.com", "password": "WrongPass1!"},
            headers={"x-forwarded-for": f"203.0.113.{index}"},
        )
    assert response.status_code == 429
    store = AuthThrottleStore(sessions)
    assert store.is_locked(store.login_ip_bucket("testclient"), now=clock["now"])
