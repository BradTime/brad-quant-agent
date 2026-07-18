"""H6：logout 递增 token_version，使 access/refresh/WS 全部失效。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.db.base import Base
from app.main import app
from app.models.auth import AuthThrottle, EmailVerification, VerificationEmailOutbox
from app.models.user import User
from app.services import auth as auth_service


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch):
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
    try:
        yield sessions
    finally:
        engine.dispose()


def _register_and_login(email: str = "revoke@example.com") -> dict:
    auth_service.register_user(email, "ValidPass1!", "Revoke")
    return auth_service.authenticate(email, "ValidPass1!")


def test_tokens_carry_version_and_logout_increments(token_env) -> None:
    data = _register_and_login()
    access = security.decode_token(data["token"])
    refresh = security.decode_token(data["refreshToken"])
    assert access is not None and refresh is not None
    assert access["tv"] == 0
    assert refresh["tv"] == 0

    assert auth_service.revoke_user_tokens(data["user"]["id"]) is True
    user = auth_service.get_user_by_id(data["user"]["id"])
    assert user is not None
    assert user.token_version == 1
    assert auth_service.user_matches_token_version(data["user"]["id"], 0) is None
    assert auth_service.user_matches_token_version(data["user"]["id"], 1) is not None


def test_refresh_rejects_revoked_token(token_env) -> None:
    data = _register_and_login("refresh-revoke@example.com")
    auth_service.revoke_user_tokens(data["user"]["id"])
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": data["refreshToken"]},
    )
    assert response.status_code == 401


def test_logout_endpoint_revokes_access_and_refresh(token_env) -> None:
    data = _register_and_login("api-revoke@example.com")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {data['token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200

    logged_out = client.post("/api/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 200

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": data["refreshToken"]},
        ).status_code
        == 401
    )

    # 重新登录签发新 version，旧令牌仍无效
    again = auth_service.authenticate("api-revoke@example.com", "ValidPass1!")
    assert again["token"] != data["token"]
    new_payload = security.decode_token(again["token"])
    assert new_payload is not None
    assert new_payload["tv"] == 1
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {again['token']}"},
        ).status_code
        == 200
    )


def test_ws_rejects_revoked_token_on_next_message(token_env) -> None:
    data = _register_and_login("ws-revoke@example.com")
    client = TestClient(app)
    with client.websocket_connect(f"/ws/v1?token={data['token']}") as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert welcome["payload"]["privateChannel"] is True

        auth_service.revoke_user_tokens(data["user"]["id"])
        ws.send_json({"type": "ping"})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert "失效" in error["payload"]["message"]
