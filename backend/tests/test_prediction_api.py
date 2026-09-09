from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app


def test_prediction_portfolio_endpoints_require_auth_and_enforce_limits():
    identity = {"user": None}

    def current_user():
        if identity["user"] is None:
            raise HTTPException(status_code=401, detail="未认证")
        return identity["user"]

    app.dependency_overrides[get_current_user] = current_user
    client = TestClient(app)
    try:
        assert client.post(
            "/api/v1/portfolio/regime",
            json={
                "indexCloses": [100] * 60,
                "marketBreadth": 0.5,
                "asOf": "2026-09-09",
            },
        ).status_code == 401
        identity["user"] = SimpleNamespace(id="user-a")
        regime = client.post(
            "/api/v1/portfolio/regime",
            json={
                "indexCloses": [100 + index for index in range(60)],
                "marketBreadth": 0.7,
                "asOf": "2026-09-09",
            },
        )
        assert regime.status_code == 200
        assert regime.json()["data"]["regime"] == "bull"
        assert regime.json()["data"]["authoritative"] is False
        assert client.post("/api/v1/portfolio/allocate", json={}).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
