from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app


def test_prediction_portfolio_endpoints_require_auth_and_enforce_limits(
    monkeypatch,
):
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
        identity["user"] = SimpleNamespace(id="user-a", role="user")
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
        monkeypatch.setattr(
            "app.services.prediction_registry.get_prediction",
            lambda code, as_of=None: {
                "code": code,
                "signalDate": "2026-09-09",
                "probabilityUp": 0.6,
            },
        )
        prediction = client.get(
            "/api/v1/predictions",
            params={"code": "600000", "asOf": "2026-09-09"},
        )
        assert prediction.status_code == 200
        assert prediction.json()["data"]["code"] == "600000.SH"
        assert (
            client.post("/api/v1/predictions/models/run-1/promote").status_code
            == 403
        )
        identity["user"] = SimpleNamespace(id="admin-a", role="admin")
        monkeypatch.setattr(
            "app.services.prediction_registry.promote_candidate",
            lambda run_id, **kwargs: {"id": run_id, "status": "champion"},
        )
        promoted = client.post("/api/v1/predictions/models/run-1/promote")
        assert promoted.status_code == 200
        monkeypatch.setattr(
            "app.services.authoritative_allocation.preview",
            lambda user_id, requested_codes, as_of: {
                "authoritative": True,
                "executionApproved": False,
                "codes": requested_codes,
            },
        )
        allocation = client.post(
            "/api/v1/portfolio/authoritative-preview",
            json={"codes": ["600000"], "asOf": "2026-09-09"},
        )
        assert allocation.status_code == 200
        assert allocation.json()["data"]["codes"] == ["600000.SH"]
        monkeypatch.setattr(
            "app.services.decision_chain.run",
            lambda user_id, codes, as_of: {
                "id": "decision-1",
                "status": "vetoed",
                "codes": codes,
            },
        )
        decision = client.post(
            "/api/v1/decisions",
            json={"codes": ["600000"], "asOf": "2026-09-09"},
        )
        assert decision.status_code == 200
        assert decision.json()["data"]["codes"] == ["600000.SH"]
        monkeypatch.setattr(
            "app.services.decision_room.state",
            lambda user_id: {
                "mode": "research_only",
                "killSwitchActive": False,
                "executionEnabled": False,
            },
        )
        monkeypatch.setattr(
            "app.services.step_up.status",
            lambda user_id: {"enabled": False, "pending": False},
        )
        room = client.get("/api/v1/decision-room")
        assert room.status_code == 200
        assert room.json()["data"]["executionEnabled"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)
