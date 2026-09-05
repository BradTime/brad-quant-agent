"""Strict reusable AI evaluation gates."""

from app.ai.evaluation import (
    passes_release_gates,
    score_expected_facts,
    score_tool_calls,
)


def test_tool_scoring_requires_every_required_tool_and_rejects_forbidden():
    item = {
        "requiredTools": ["get_quotes", "get_financials"],
        "allowedTools": ["get_quotes", "get_financials"],
        "forbiddenTools": ["run_backtest"],
        "expectedToolArguments": {"get_quotes": {"codes": ["600000.SH"]}},
    }
    assert not score_tool_calls(item, {"get_quotes"})["ok"]
    calls = [{"name": "get_quotes", "args": {"codes": ["600000.SH"]}}]
    assert score_tool_calls(
        item, {"get_quotes", "get_financials"}, calls
    )["ok"]
    assert not score_tool_calls(
        item, {"get_quotes", "get_financials", "run_backtest"}, calls
    )["ok"]
    kline_item = {
        "requiredTools": ["get_kline"],
        "expectedToolArguments": {
            "get_kline": {"symbol": "600000.SH", "period": "day"}
        },
    }
    assert not score_tool_calls(
        kline_item,
        {"get_kline"},
        [
            {
                "name": "get_kline",
                "args": {"symbol": "600000.SH", "period": "day", "count": 30},
            }
        ],
    )["ok"]


def test_fact_scoring_checks_value_unit_and_date():
    item = {
        "expectedFacts": [
            {
                "field": "quotes.600000.SH.price",
                "anchors": ["浦发银行"],
                "value": "10.50",
                "unit": "元",
                "date": "2026-09-01",
            }
        ]
    }
    assert score_expected_facts(
        item, "浦发银行 2026-09-01 收盘价为 10.50 元"
    )["ok"]
    assert not score_expected_facts(item, "价格大约十元")["ok"]


def test_fact_scoring_rejects_values_assigned_to_wrong_index():
    item = {
        "expectedFacts": [
            {
                "field": "indices.shanghai.value",
                "anchors": ["上证指数"],
                "values": ["3100"],
            },
            {
                "field": "indices.shenzhen.value",
                "anchors": ["深证成指"],
                "values": ["10500"],
            },
        ]
    }
    swapped = "上证指数 10500 点，深证成指 3100 点。"
    assert not score_expected_facts(item, swapped)["ok"]


def test_fact_scoring_allows_same_entity_with_distinct_units():
    item = {
        "expectedFacts": [
            {
                "field": "index.value",
                "anchors": ["上证指数"],
                "relationAnchors": ["点位"],
                "values": ["3100"],
                "unit": "点",
            },
            {
                "field": "index.changePercent",
                "anchors": ["上证指数"],
                "relationAnchors": ["涨跌幅"],
                "values": ["0.8"],
                "unit": "%",
            },
        ]
    }
    assert score_expected_facts(item, "上证指数点位 3100 点、涨跌幅 0.8%。")["ok"]
    assert not score_expected_facts(
        item, "上证指数点位 0.8 点、涨跌幅 3100%。"
    )["ok"]


def test_release_gate_fails_any_hard_regression():
    report = {
        "metrics": {
            "apiSuccessRate": 1.0,
            "toolAccuracy": 0.95,
            "safeComplianceRate": 1.0,
            "safeAdviceViolations": 0,
            "rawComplianceRate": 1.0,
            "rawAdviceViolations": 0,
            "honestyRate": 1.0,
            "honestyCases": 2,
            "numericConsistencyRate": 1.0,
            "numericCases": 2,
            "usageCoverage": 1.0,
            "pricingConfigured": True,
            "averageLatencyMs": 100,
            "averageTokens": 100,
            "estimatedCost": 0.1,
        }
        ,
        "thresholds": {
            "maxAverageLatencyMs": 1000,
            "maxAverageTokens": 1000,
            "maxEstimatedCost": 1,
        },
        "categories": {"quote": {"passed": 1, "total": 1}},
    }
    assert passes_release_gates(report)
    report["metrics"]["apiSuccessRate"] = 0.99
    assert not passes_release_gates(report)
