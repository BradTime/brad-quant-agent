"""Argument-aware frozen AI evaluation fixtures."""

from pathlib import Path

from scripts.ai_eval import (
    frozen_tool_executor,
    load_dataset,
    validate_baseline_report,
)


def test_fixture_filters_invalid_symbol_and_historical_pit_queries():
    execute = frozen_tool_executor()
    assert execute("get_news", {"code": "999999.SH", "limit": 20})["news"] == []
    assert (
        execute(
            "get_financials",
            {"code": "600000.SH", "limit": 12, "asOf": "2024-03-31"},
        )["financials"]
        == []
    )


def test_fixture_honors_alternate_symbol_profile_and_exact_quote_codes():
    execute = frozen_tool_executor()
    profile = execute("get_stock_profile", {"code": "600036.SH"})["profile"]
    assert profile["name"] == "招商银行"
    quotes = execute(
        "get_quotes", {"codes": ["000001.SZ", "600036.SH"]}
    )["quotes"]
    assert [row["code"] for row in quotes] == ["000001.SZ", "600036.SH"]


def test_fixture_applies_kline_count_and_rejects_unknown_argument():
    execute = frozen_tool_executor()
    assert len(
        execute(
            "get_kline",
            {"symbol": "600000.SH", "period": "day", "count": 2},
        )["kline"]
    ) == 2
    try:
        execute("get_quotes", {"codes": ["600000.SH"], "unknown": True})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid fixture arguments must be rejected")


def test_fixture_supports_corpus_profiles_and_amount_filters():
    execute = frozen_tool_executor()
    assert (
        execute("get_stock_profile", {"code": "688001.SH"})["profile"]["name"]
        == "华兴源创"
    )
    assert (
        execute("get_stock_profile", {"code": "430047.BJ"})["profile"]["name"]
        == "诺思兰德"
    )
    active = execute("screen_stocks", {"amountMin": 5_000_000_000.0})
    assert [row["code"] for row in active["items"]] == ["600000.SH"]
    empty = execute("screen_stocks", {"amountMin": 7_000_000_000.0})
    assert empty["items"] == []


def test_failed_reference_baseline_is_valid_but_cannot_be_promoted():
    baseline = (
        Path(__file__).resolve().parent
        / "reports"
        / "ai_eval_baseline_20260902.json"
    )
    data = load_dataset()
    assert validate_baseline_report(data, baseline) == 0
    assert validate_baseline_report(data, baseline, require_passing=True) == 1
