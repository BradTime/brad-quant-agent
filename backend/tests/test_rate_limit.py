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
