"""Tests for refresh rate limiting."""

from __future__ import annotations

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
