"""Tests for AI tool dispatch (offline, no DB/network)."""

from __future__ import annotations

from unittest.mock import patch

from app.ai.tools import execute_tool
from app.providers.base import QuoteDTO


def test_unknown_tool_returns_error():
    out = execute_tool("no_such_tool", {})
    assert "error" in out


def test_screen_stocks_passes_volume_filters():
    fake_quote = QuoteDTO(
        code="600000.SH",
        name="浦发银行",
        price=8.0,
        change=0.1,
        change_percent=1.2,
        volume=5000.0,
        amount=1e8,
    )
    with patch("app.ai.tools.market._ensure_stocks", return_value=[fake_quote]):
        out = execute_tool(
            "screen_stocks",
            {"volumeMin": 1000, "changePercentMin": 0, "limit": 10},
        )
    assert out["total"] == 1
    assert out["stocks"][0]["code"] == "600000.SH"


def test_get_quotes_uses_get_quote_per_code():
    with patch(
        "app.ai.tools.market.get_quote",
        side_effect=lambda c: {"code": c, "price": 10.0, "stale": True},
    ) as mock_get:
        out = execute_tool("get_quotes", {"codes": ["600000", "000001.SZ"]})
    assert mock_get.call_count == 2
    assert len(out["quotes"]) == 2
