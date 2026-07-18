"""Focused tests for persisted multi-agent trace details."""

from __future__ import annotations

import time

from app.agents import brief_graph
from app.ai.compliance import find_advice_flags


def test_trace_includes_node_input_and_output():
    trace = brief_graph._trace(
        "market",
        time.time(),
        "市场分析结论",
        human="真实数据包",
    )

    assert trace["input"] == "真实数据包"
    assert trace["output"] == "市场分析结论"


def test_trace_caps_persisted_input_and_output():
    content = "数" * 2000

    trace = brief_graph._trace("news", time.time(), content, human=content)

    assert len(trace["input"]) == 1500
    assert len(trace["output"]) == 1500


def test_trace_omits_input_when_node_has_no_human_prompt():
    trace = brief_graph._trace("reviewer", time.time(), "合规通过")

    assert "input" not in trace
    assert trace["output"] == "合规通过"


def test_trace_input_keeps_node_specific_tail():
    human = "公共数据包" + ("数" * 1800) + "评审反馈尾部"

    trace = brief_graph._trace("evaluator", time.time(), "通过", human=human)

    assert trace["input"].endswith("评审反馈尾部")
    assert not trace["input"].startswith("公共数据包")


def test_trace_base_input_keeps_both_market_context_edges():
    human = "指数与自选股开头" + ("数" * 1800) + "新闻与知识尾部"

    trace = brief_graph._trace("market", time.time(), "分析", human=human)

    assert trace["input"].startswith("指数与自选股开头")
    assert trace["input"].endswith("新闻与知识尾部")
    assert len(trace["input"]) <= 1500


def test_trace_never_persists_advice_redflags():
    trace = brief_graph._trace(
        "editor",
        time.time(),
        "建议买入并全仓",
        human="上一版草稿建议卖出",
    )

    assert find_advice_flags(trace["input"]) == []
    assert find_advice_flags(trace["output"]) == []
