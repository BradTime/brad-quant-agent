"""Tests for AI compliance runtime guards."""

from __future__ import annotations

from app.ai.compliance import (
    DISCLAIMER_HINT,
    enforce_compliance,
    find_advice_flags,
    stream_compliance_tail,
)


def test_enforce_adds_disclaimer():
    out = enforce_compliance("浦发银行现价 10.5 元。")
    assert DISCLAIMER_HINT in out


def test_enforce_replaces_advice():
    out = enforce_compliance("这只股票建议买入，必涨。")
    assert find_advice_flags(out) == []
    assert DISCLAIMER_HINT in out
    assert "建议买入" not in out


def test_stream_tail_appends_disclaimer():
    tail = stream_compliance_tail("客观数据说明。")
    assert DISCLAIMER_HINT in tail


def test_stream_tail_warns_on_advice():
    tail = stream_compliance_tail("应该买入这只。")
    assert "合规提示" in tail
    assert DISCLAIMER_HINT in tail
