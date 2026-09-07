"""Tests for refresh rate limiting."""

from __future__ import annotations

import pytest

from app.core import redis_client
from app.services import market
from app.services import rate_limit as rl


def test_refresh_cooldown_blocks_second_call():
    rl._LAST_REFRESH.clear()
    assert rl.seconds_until_refresh_allowed("u1", "600000.SH") is None
    rl.mark_refresh("u1", "600000.SH")
    wait = rl.seconds_until_refresh_allowed("u1", "600000.SH")
    assert wait is not None
    assert wait > 0


def test_refresh_cooldown_isolated_by_user():
    rl._LAST_REFRESH.clear()
    rl.mark_refresh("u1", "600000.SH")
    assert rl.seconds_until_refresh_allowed("u2", "600000.SH") is None


def test_refresh_symbol_variants_have_one_canonical_cooldown_key():
    assert market.canonical_stock_code("600000") == "600000.SH"
    assert market.canonical_stock_code("600000.sh") == "600000.SH"
    with pytest.raises(ValueError, match="交易所"):
        market.canonical_stock_code("600000.SZ")


def _reset_gate():
    rl._DAILY_COUNTS.clear()
    rl._LAST_HEAVY.clear()


def test_ai_cost_gate_daily_quota():
    _reset_gate()
    assert rl.ai_cost_gate("u1", "chat", quota=2, interval=0) is None
    assert rl.ai_cost_gate("u1", "chat", quota=2, interval=0) is None
    msg = rl.ai_cost_gate("u1", "chat", quota=2, interval=0)
    assert msg is not None and "额度" in msg


def test_ai_cost_gate_unlimited_when_quota_zero():
    _reset_gate()
    for _ in range(5):
        assert rl.ai_cost_gate("u1", "chat", quota=0, interval=0) is None


def test_ai_cost_gate_heavy_interval():
    _reset_gate()
    assert rl.ai_cost_gate("u1", "brief", quota=0, interval=10) is None
    msg = rl.ai_cost_gate("u1", "brief", quota=0, interval=10)
    assert msg is not None and "频繁" in msg


def test_ai_cost_gate_isolated_by_user_and_bucket():
    _reset_gate()
    assert rl.ai_cost_gate("u1", "chat", quota=1, interval=0) is None
    assert rl.ai_cost_gate("u1", "chat", quota=1, interval=0) is not None  # u1 用尽
    assert rl.ai_cost_gate("u2", "chat", quota=1, interval=0) is None  # 另一用户独立
    assert rl.ai_cost_gate("u1", "research", quota=1, interval=0) is None  # 另一桶独立


class FakeRedis:
    def __init__(self, responses: list[list[int]] | None = None):
        self.responses = list(responses or [])
        self.calls: list[tuple] = []
        self.ttl_ms = -2

    def register_script(self, script):
        def run(*, keys, args, client):
            self.calls.append((script, keys, args, client))
            return self.responses.pop(0)

        return run

    def pttl(self, key):
        self.calls.append(("pttl", key))
        return self.ttl_ms

    def set(self, key, value, px=None, nx=False):
        self.calls.append(("set", key, value, px, nx))
        return True


def test_ai_cost_gate_maps_atomic_redis_results(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeRedis([[0, 0], [1, 2500], [2, 2]])
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://test")
    monkeypatch.setattr(redis_client, "_sync_client", fake)

    assert rl.ai_cost_gate("u1", "brief", quota=2, interval=10) is None
    assert "3 秒" in (rl.ai_cost_gate("u1", "brief", quota=2, interval=10) or "")
    assert "额度" in (rl.ai_cost_gate("u1", "brief", quota=2, interval=10) or "")

    _, keys, _args, _client = fake.calls[0]
    assert len(keys) == 2
    assert keys[0] != keys[1]
    assert "u1" not in keys[0] and "brief" in keys[0]
    assert "{" in keys[0] and "}" in keys[0]


def test_refresh_cooldown_uses_shared_redis_ttl(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeRedis()
    fake.ttl_ms = 2500
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://test")
    monkeypatch.setattr(redis_client, "_sync_client", fake)

    assert rl.seconds_until_refresh_allowed("u1", "600000.SH") == 2.5
    rl.mark_refresh("u1", "600000.SH")
    assert any(call[0] == "set" and call[3] == 60_000 for call in fake.calls)


def test_refresh_cooldown_reservation_is_atomic(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_client.settings, "redis_url", "redis://test")
    monkeypatch.setattr(redis_client, "_sync_client", fake)

    assert rl.acquire_refresh_cooldown("u1", "600000.SH") is None
    assert any(call[0] == "set" and call[-1] is True for call in fake.calls)
