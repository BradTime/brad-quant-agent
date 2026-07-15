"""Strategy CRUD API tests: persistence, validation, and tenant isolation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.main import app
from app.models.strategy import Strategy
from app.services import strategy as strategy_service


@pytest.fixture
def strategy_client(monkeypatch):
    """Run strategy persistence against an isolated in-memory database."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    monkeypatch.setattr(strategy_service, "SessionLocal", test_session)
    Strategy.__table__.create(bind=engine)

    identity = {"user_id": "user-a"}

    def current_user():
        if identity["user_id"] is None:
            raise HTTPException(status_code=401, detail="未认证")
        return SimpleNamespace(id=identity["user_id"])

    app.dependency_overrides[get_current_user] = current_user
    client = TestClient(app)
    try:
        yield client, identity
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        engine.dispose()


def _create(
    client: TestClient,
    *,
    name: str = "双均线策略",
    builtin_type: str = "dual_ma",
    params: dict | None = None,
):
    return client.post(
        "/api/v1/strategies",
        json={
            "name": name,
            "description": "仅使用受支持的内置策略",
            "builtinType": builtin_type,
            "params": params if params is not None else {},
        },
    )


def test_all_strategy_routes_require_auth(strategy_client):
    client, identity = strategy_client
    identity["user_id"] = None

    assert client.get("/api/v1/strategies").status_code == 401
    assert _create(client).status_code == 401


def test_strategy_crud_and_status_transitions(strategy_client):
    client, _ = strategy_client

    created_response = _create(
        client,
        params={"fast": 10, "slow": 30, "target": 0.8},
    )
    assert created_response.status_code == 200
    created = created_response.json()["data"]
    strategy_id = created["id"]
    assert created["builtinType"] == "dual_ma"
    assert created["category"] == "trend_following"
    assert created["status"] == "draft"
    assert created["params"] == {"fast": 10, "slow": 30, "target": 0.8}
    assert "code" not in created

    listed = client.get("/api/v1/strategies").json()["data"]
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == strategy_id

    detail = client.get(f"/api/v1/strategies/{strategy_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == "双均线策略"

    updated_response = client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "name": "RSI 策略",
            "description": "更新后的策略",
            "builtinType": "rsi",
            "params": {"period": 12, "low": 25, "high": 75, "target": 0.7},
        },
    )
    assert updated_response.status_code == 200
    updated = updated_response.json()["data"]
    assert updated["name"] == "RSI 策略"
    assert updated["builtinType"] == "rsi"
    assert updated["category"] == "mean_reversion"
    assert updated["params"]["period"] == 12

    enabled = client.post(f"/api/v1/strategies/{strategy_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["data"]["status"] == "active"

    disabled = client.post(f"/api/v1/strategies/{strategy_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["data"]["status"] == "disabled"

    removed = client.delete(f"/api/v1/strategies/{strategy_id}")
    assert removed.status_code == 200
    assert removed.json()["data"] == {"deleted": True}
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 404


def test_strategy_list_supports_pagination_filters_and_search(strategy_client):
    client, _ = strategy_client
    first = _create(client, name="Alpha 趋势", builtin_type="dual_ma")
    second = _create(client, name="Beta 反转", builtin_type="rsi")
    assert first.status_code == second.status_code == 200
    client.post(f"/api/v1/strategies/{second.json()['data']['id']}/enable")

    page = client.get(
        "/api/v1/strategies",
        params={"page": 1, "pageSize": 1, "sortBy": "name", "sortOrder": "asc"},
    ).json()["data"]
    assert page["total"] == 2
    assert [item["name"] for item in page["items"]] == ["Alpha 趋势"]

    searched = client.get(
        "/api/v1/strategies",
        params={"search": "反转", "status": "active", "builtinType": "rsi"},
    ).json()["data"]
    assert searched["total"] == 1
    assert searched["items"][0]["name"] == "Beta 反转"

    category = client.get(
        "/api/v1/strategies",
        params={"category": "trend_following"},
    ).json()["data"]
    assert category["total"] == 1
    assert category["items"][0]["builtinType"] == "dual_ma"


def test_cross_user_cannot_see_or_mutate_strategy(strategy_client):
    client, identity = strategy_client
    created = _create(client).json()["data"]
    strategy_id = created["id"]

    identity["user_id"] = "user-b"
    assert client.get("/api/v1/strategies").json()["data"] == {"items": [], "total": 0}
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 404
    assert client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={"name": "越权修改"},
    ).status_code == 404
    assert client.delete(f"/api/v1/strategies/{strategy_id}").status_code == 404
    assert client.post(f"/api/v1/strategies/{strategy_id}/enable").status_code == 404
    assert client.post(f"/api/v1/strategies/{strategy_id}/disable").status_code == 404
    assert client.post(f"/api/v1/strategies/{strategy_id}/duplicate").status_code == 404

    identity["user_id"] = "user-a"
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 200


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"builtinType": "custom"}, "builtin"),
        ({"params": {"fast": 5, "slow": 20, "target": 0.9, "mystery": 1}}, "参数"),
        ({"params": {"fast": 0, "slow": 20, "target": 0.9}}, "范围"),
        ({"params": {"fast": 5.5, "slow": 20, "target": 0.9}}, "整数"),
        ({"params": {"fast": 30, "slow": 10, "target": 0.9}}, "fast"),
        ({"code": "raise RuntimeError('unsafe')"}, "请求参数"),
    ],
)
def test_strategy_rejects_invalid_or_executable_input(strategy_client, payload, message):
    client, _ = strategy_client
    body = {
        "name": "无效策略",
        "builtinType": "dual_ma",
        "params": {"fast": 5, "slow": 20, "target": 0.9},
        **payload,
    }

    response = client.post("/api/v1/strategies", json=body)

    assert response.status_code == 400
    assert message in response.json()["message"]


def test_strategy_rejects_inverted_rsi_thresholds(strategy_client):
    client, _ = strategy_client

    response = _create(
        client,
        builtin_type="rsi",
        params={"period": 14, "low": 50, "high": 50, "target": 0.9},
    )

    assert response.status_code == 400
    assert "low" in response.json()["message"]


def test_duplicate_copies_configuration_into_new_draft(strategy_client):
    client, _ = strategy_client
    source = _create(
        client,
        name="动量精选",
        builtin_type="momentum",
        params={"lookback": 35, "target": 0.85},
    ).json()["data"]
    client.post(f"/api/v1/strategies/{source['id']}/enable")

    response = client.post(f"/api/v1/strategies/{source['id']}/duplicate")

    assert response.status_code == 200
    copied = response.json()["data"]
    assert copied["id"] != source["id"]
    assert copied["name"] == "动量精选（副本）"
    assert copied["builtinType"] == source["builtinType"]
    assert copied["params"] == source["params"]
    assert copied["status"] == "draft"
    assert client.get("/api/v1/strategies").json()["data"]["total"] == 2
