"""Training API ownership and minimal admin authorization."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.services import training_data
from app.services.auth import serialize_user


def test_admin_role_is_exposed_to_server_side_layout():
    user = SimpleNamespace(
        id="admin-a",
        email="admin@example.com",
        name="Admin",
        role="admin",
        created_at=None,
        updated_at=None,
    )
    assert serialize_user(user)["role"] == "admin"


def test_non_admin_cannot_list_training_candidates():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-a", role="user"
    )
    try:
        response = TestClient(app).get("/api/v1/training/admin/candidates")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_admin_can_list_training_candidates(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="admin-a", role="admin"
    )
    monkeypatch.setattr(training_data, "list_candidates", lambda _status, _limit: [])
    try:
        response = TestClient(app).get("/api/v1/training/admin/candidates")
        assert response.status_code == 200
        assert response.json()["data"] == []
    finally:
        app.dependency_overrides.clear()
