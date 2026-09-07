"""M20: HttpOnly cookie session + Cookie/Bearer dual auth."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.core.auth_cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.db.base import Base
from app.main import app
from app.models.auth import AuthThrottle, EmailVerification, VerificationEmailOutbox
from app.models.user import User
from app.services import auth as auth_service


@pytest.fixture
def cookie_client(monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr(auth_service, "SessionLocal", sessions)
    monkeypatch.setattr(auth_service.settings, "auth_auto_verify_registration", True)
    auth_service.register_user("cookie@example.com", "ValidPass1!", "Cookie")
    try:
        yield TestClient(app)
    finally:
        engine.dispose()


def test_login_sets_httponly_cookies_without_tokens_in_body(cookie_client: TestClient):
    response = cookie_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "ValidPass1!"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "user" in data
    assert "token" not in data
    assert "refreshToken" not in data
    assert response.cookies.get(ACCESS_COOKIE)
    assert response.cookies.get(REFRESH_COOKIE)
    # Set-Cookie must be HttpOnly
    set_cookie = ",".join(response.headers.get_list("set-cookie"))
    assert "HttpOnly" in set_cookie or "httponly" in set_cookie.lower()


def test_me_accepts_access_cookie_without_bearer(cookie_client: TestClient):
    login = cookie_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "ValidPass1!"},
    )
    assert login.status_code == 200
    me = cookie_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "cookie@example.com"


def test_refresh_from_cookie_rotates_without_body(cookie_client: TestClient):
    cookie_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "ValidPass1!"},
    )
    old_refresh = cookie_client.cookies.get(REFRESH_COOKIE)
    refreshed = cookie_client.post("/api/v1/auth/refresh", json={})
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["user"]["email"] == "cookie@example.com"
    new_refresh = cookie_client.cookies.get(REFRESH_COOKIE)
    assert new_refresh and new_refresh != old_refresh


def test_logout_clears_cookies(cookie_client: TestClient):
    cookie_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "ValidPass1!"},
    )
    out = cookie_client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    # TestClient may retain jar; deleted cookies typically empty string
    assert cookie_client.get("/api/v1/auth/me").status_code == 401


def test_ws_ticket_requires_session(
    cookie_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    denied = cookie_client.get("/api/v1/auth/ws-ticket")
    assert denied.status_code == 401
    cookie_client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "ValidPass1!"},
    )
    monkeypatch.setattr(security.settings, "ws_ticket_expire_seconds", 999)
    ticket = cookie_client.get("/api/v1/auth/ws-ticket")
    assert ticket.status_code == 200
    token = ticket.json()["data"]["token"]
    payload = security.decode_token(token)
    assert payload is not None
    assert payload["type"] == "ws"
    assert payload["exp"] - payload["iat"] == 120


def test_bearer_still_works_for_scripts(cookie_client: TestClient):
    tokens = auth_service.authenticate("cookie@example.com", "ValidPass1!")
    me = cookie_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['token']}"},
    )
    assert me.status_code == 200
