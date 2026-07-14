"""Tests for morning-brief data-pack correctness."""

from __future__ import annotations

from unittest.mock import patch

from app.services import brief


def test_render_data_pack_uses_index_value_field():
    text = brief.render_data_pack_text(
        {
            "tradeDate": "2026-05-31",
            "scope": "global",
            "indices": [{"name": "上证指数", "value": 3123.45, "changePercent": 1.23}],
            "watchlist": {"count": 0},
            "capitalFlow": [],
            "dragonTiger": [],
            "news": [],
            "coverage": {"missing": []},
        }
    )

    assert "3123.45" in text
    assert "上证指数" in text


def test_build_data_pack_uses_cache_only_indices():
    with (
        patch("app.services.brief.market.indices_snapshot", return_value=[]) as snapshot,
        patch("app.services.brief.market.get_market_overview") as live_overview,
        patch("app.services.brief.watchlist.list_items", return_value=[]),
        patch("app.services.brief._recent_dragon_tiger", return_value=[]),
        patch("app.services.brief._recent_news", return_value=[]),
    ):
        pack = brief.build_data_pack("user-1")

    assert pack["indices"] == []
    snapshot.assert_called_once()
    live_overview.assert_not_called()


def test_build_data_pack_scopes_news_to_watchlist_codes():
    watch_items = [
        {"code": "600000.SH", "name": "浦发银行", "changePercent": 1.0},
        {"code": "000001.SZ", "name": "平安银行", "changePercent": -0.5},
    ]
    with (
        patch("app.services.brief.market.indices_snapshot", return_value=[]),
        patch("app.services.brief.watchlist.list_items", return_value=watch_items),
        patch("app.services.brief.market.get_capital_flow", return_value=[]),
        patch("app.services.brief._recent_dragon_tiger", return_value=[]),
        patch("app.services.brief._recent_news", return_value=[]) as news,
    ):
        brief.build_data_pack("user-1")

    news.assert_called_once_with(["600000.SH", "000001.SZ"])


def test_bounded_trace_details_keeps_every_node_within_total_budget():
    trace = [
        {
            "node": f"node-{i}",
            "input": "输入" * 1500,
            "output": "输出" * 1500,
        }
        for i in range(14)
    ]

    bounded = brief._bounded_trace_details(trace)

    assert all(row["input"] and row["output"] for row in bounded)
    assert sum(len(row["input"]) + len(row["output"]) for row in bounded) <= 18_000
