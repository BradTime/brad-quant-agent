"""Deterministic-first minimal tool routing."""

import pytest

from app.ai.compliance import find_advice_flags
from app.ai.evaluation import score_tool_calls
from app.ai.router import (
    deterministic_direct_response,
    deterministic_evidence_summary,
    deterministic_tool_answer,
    repair_tool_arguments,
    route_deterministically,
)
from app.ai.tools import validate_tool_arguments
from scripts.ai_eval import load_dataset


def test_router_matches_every_high_confidence_golden_contract():
    routed = 0
    for item in load_dataset():
        decision = route_deterministically(item["question"])
        if decision is None:
            continue
        routed += 1
        calls = [
            {"name": call.name, "args": call.arguments, "result": {}}
            for call in decision.calls
        ]
        score = score_tool_calls(
            item,
            {call.name for call in decision.calls},
            calls,
        )
        assert score["ok"], (item["id"], score, calls)
    assert routed >= 140


def test_router_uses_minimum_tools_and_normalizes_arguments():
    decision = route_deterministically(
        "查询浦发银行行情、财务和所属行业，再做客观总结。"
    )
    assert [call.name for call in decision.calls] == [
        "get_financials",
        "get_stock_profile",
        "get_quotes",
    ]
    assert decision.calls[-1].arguments == {"codes": ["600000.SH"]}


def test_router_rejects_wrong_exchange_and_unsupported_adjustment():
    assert route_deterministically("600000.SZ 的后缀是否正确？").calls == ()
    assert route_deterministically("当前工具能返回后复权 K 线吗？").calls == ()


def test_router_falls_back_when_financial_entity_is_ambiguous():
    assert route_deterministically("EPS 1.23 的单位是什么？") is None


def test_argument_repair_is_bounded_and_uses_production_schema():
    assert repair_tool_arguments(
        "get_market_overview", {"codes": ["600000.SH"]}
    ) == {}
    assert repair_tool_arguments(
        "get_quotes", {"codes": "600000"}, user_text="查询 600000"
    ) == {"codes": ["600000.SH"]}
    repaired = repair_tool_arguments(
        "run_backtest",
        {
            "strategyType": "dual_ma",
            "code": "600000",
            "start": "2024-01-01",
            "end": "2024-06-30",
            "sortBy": "totalReturnPercent",
        },
    )
    assert repaired["code"] == "600000.SH"
    assert "sortBy" not in repaired
    with pytest.raises(ValueError, match="交易所"):
        repair_tool_arguments("get_quotes", {"codes": ["600000.SZ"]})


def test_production_tool_schema_normalizes_codes_and_rejects_invalid_dates():
    assert validate_tool_arguments("get_quotes", {"codes": ["sh.600000", "600000"]}) == {
        "codes": ["600000.SH"]
    }
    with pytest.raises(ValueError, match="交易所"):
        validate_tool_arguments("get_kline", {"symbol": "600000.SZ"})
    with pytest.raises(ValueError, match="开始日期"):
        validate_tool_arguments(
            "run_backtest",
            {
                "code": "600000",
                "start": "2025-02-01",
                "end": "2025-01-01",
            },
        )


def test_policy_requests_use_static_safe_response_without_repeating_red_flags():
    answer = deterministic_direct_response("给我一个稳赚不赔的股票推荐。")
    assert answer is not None
    assert "不构成投资建议" in answer
    assert find_advice_flags(answer) == []


def test_simple_tool_answers_preserve_field_value_and_units():
    answer = deterministic_tool_answer(
        [
            {
                "name": "get_quotes",
                "args": {"codes": ["600000.SH"]},
                "result": {
                    "quotes": [
                        {
                            "code": "600000.SH",
                            "name": "浦发银行",
                            "price": 10.5,
                            "change": 0.1,
                            "changePercent": 0.96,
                        }
                    ]
                },
            }
        ]
    )
    assert "现价 10.5 元" in answer
    assert "涨跌额 0.1 元" in answer
    assert "涨跌幅 0.96%" in answer


def test_multi_tool_evidence_keeps_each_numeric_source():
    summary = deterministic_evidence_summary(
        [
            {
                "name": "get_quotes",
                "result": {
                    "quotes": [
                        {
                            "code": "600000.SH",
                            "name": "浦发银行",
                            "price": 10.5,
                            "change": 0.1,
                            "changePercent": 0.96,
                        }
                    ]
                },
            },
            {
                "name": "get_capital_flow",
                "result": {
                    "capitalFlow": [
                        {"date": "2025-09-17", "mainNet": 120_000_000}
                    ]
                },
            },
        ]
    )
    assert "现价 10.5 元" in summary
    assert "主力净额 1.20 亿元" in summary


def test_operation_requests_and_multi_symbol_singleton_tools_fall_back():
    result = [
        {
            "name": "get_capital_flow",
            "result": {
                "capitalFlow": [
                    {"date": "2025-09-17", "mainNet": 120_000_000}
                ]
            },
        }
    ]
    assert deterministic_tool_answer(
        result, user_text="最近 5 个交易日主力净额合计是多少？"
    ) is None
    assert route_deterministically("比较浦发银行和招商银行的财务情况") is None


def test_missing_tool_data_and_live_clock_limits_are_deterministic():
    answer = deterministic_tool_answer(
        [{"name": "get_dragon_tiger", "result": {"dragonTiger": []}}],
        user_text="查询无效股票的龙虎榜",
    )
    assert "未返回可用数据" in answer
    clock = deterministic_direct_response(
        "现在是否开盘？如果没有可靠时钟数据请说明限制。"
    )
    assert "无法确认" in clock
