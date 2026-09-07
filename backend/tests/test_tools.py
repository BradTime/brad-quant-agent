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


def test_tool_rejects_oversized_codes_and_limits():
    too_many = execute_tool("get_quotes", {"codes": [f"{i:06d}" for i in range(21)]})
    assert too_many["error"] == "工具参数无效"

    huge_kline = execute_tool("get_kline", {"symbol": "600000.SH", "count": 10_000})
    assert huge_kline["error"] == "工具参数无效"

    huge_rag = execute_tool("search_knowledge", {"query": "白酒", "k": 999})
    assert huge_rag["error"] == "工具参数无效"

    nan_screen = execute_tool("screen_stocks", {"priceMin": float("nan")})
    assert nan_screen["error"] == "工具参数无效"

    extra = execute_tool("get_stock_profile", {"code": "600000.SH", "hack": 1})
    assert extra["error"] == "工具参数无效"


def test_tool_clamps_valid_bounds_and_dispatches():
    with patch(
        "app.ai.tools.market.get_kline",
        return_value={"bars": [], "dataQuality": "missing", "meta": {}},
    ) as mock_k:
        out = execute_tool("get_kline", {"symbol": "600000.SH", "count": 500})
    assert "error" not in out
    mock_k.assert_called_once_with("600000.SH", "day", 500)

    with patch("app.services.rag.retrieve", return_value=[{"text": "x"}]) as mock_retrieve:
        out = execute_tool("search_knowledge", {"query": "政策", "k": 5})
    assert out["results"] == [{"text": "x"}]
    mock_retrieve.assert_called_once_with("政策", 5)


def test_run_backtest_rejects_unknown_strategy_and_dispatches():
    bad = execute_tool(
        "run_backtest",
        {
            "strategyType": "magic",
            "code": "600000.SH",
            "start": "2024-01-01",
            "end": "2024-06-01",
        },
    )
    assert bad["error"] == "工具参数无效"

    with patch(
        "app.backtest.runner.run_backtest",
        return_value={
            "metrics": {"sharpeRatio": 1.2, "totalReturnPercent": 10.0},
            "dataQuality": {"600000.SH": "full"},
        },
    ) as mock_run:
        out = execute_tool(
            "run_backtest",
            {
                "strategyType": "dual_ma",
                "code": "600000.SH",
                "start": "2024-01-01",
                "end": "2024-06-01",
                "params": {"fast": 5, "slow": 20},
            },
        )
    assert "error" not in out or out.get("error") is None
    assert out["metrics"]["sharpeRatio"] == 1.2
    mock_run.assert_called_once()


def test_grid_search_rejects_oversized_grid_and_returns_top():
    huge = execute_tool(
        "grid_search",
        {
            "code": "600000.SH",
            "start": "2024-01-01",
            "end": "2024-06-01",
            "paramGrid": {"fast": list(range(1, 11)), "slow": list(range(20, 30))},
        },
    )
    assert huge["error"] == "工具参数无效"

    with patch(
        "app.services.backtest_run.grid_search",
        return_value={
            "results": [
                {"params": {"fast": 5, "slow": 20}, "metrics": {"sharpeRatio": 1.5}},
                {"params": {"fast": 10, "slow": 60}, "metrics": {"sharpeRatio": 0.8}},
            ],
            "best": {"params": {"fast": 5, "slow": 20}, "metrics": {"sharpeRatio": 1.5}},
        },
    ):
        out = execute_tool(
            "grid_search",
            {
                "code": "600000.SH",
                "start": "2024-01-01",
                "end": "2024-06-01",
                "paramGrid": {"fast": [5, 10], "slow": [20, 60]},
                "topN": 1,
            },
        )
    assert len(out["top"]) == 1
    assert out["best"]["params"]["fast"] == 5

