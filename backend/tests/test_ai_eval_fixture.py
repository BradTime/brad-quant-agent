"""Argument-aware frozen AI evaluation fixtures."""

import copy
import json
from pathlib import Path

from scripts.ai_eval import (
    frozen_tool_executor,
    load_dataset,
    recompute_report_metrics,
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
    assert (
        validate_baseline_report(
            data,
            baseline,
            junit_path=baseline.with_suffix(".xml"),
        )
        == 0
    )
    assert validate_baseline_report(data, baseline, require_passing=True) == 1


def test_report_gate_rejects_forged_rows_and_junit_mismatch(tmp_path):
    reports = Path(__file__).resolve().parent / "reports"
    baseline = reports / "ai_eval_baseline_20260902.json"
    report = json.loads(baseline.read_text(encoding="utf-8"))
    forged = copy.deepcopy(report)
    forged["results"][0]["ok"] = not forged["results"][0]["ok"]
    forged_path = tmp_path / "forged.json"
    forged_path.write_text(json.dumps(forged), encoding="utf-8")
    assert validate_baseline_report(load_dataset(), forged_path) == 1

    mismatched_junit = tmp_path / "mismatched.xml"
    junit = (reports / "ai_eval_baseline_20260902.xml").read_text(encoding="utf-8")
    mismatched_junit.write_text(
        junit.replace('failures="85"', 'failures="84"', 1),
        encoding="utf-8",
    )
    assert (
        validate_baseline_report(
            load_dataset(),
            baseline,
            junit_path=mismatched_junit,
        )
        == 1
    )


def test_report_gate_rejects_malformed_json_shape(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"schemaVersion": 1, "results": []}', encoding="utf-8")
    assert validate_baseline_report(load_dataset(), malformed) == 1


def test_candidate_metrics_recompute_zero_token_deterministic_rows(tmp_path):
    baseline = (
        Path(__file__).resolve().parent
        / "reports"
        / "ai_eval_baseline_20260902.json"
    )
    report = json.loads(baseline.read_text(encoding="utf-8"))
    report["pricing"] = {
        "inputCostPerMillion": 1.0,
        "outputCostPerMillion": 2.0,
    }
    for row in report["results"]:
        row["latencyMs"] = 1
        row["usage"] = {"promptTokens": 0, "completionTokens": 0}
    recomputed = recompute_report_metrics(load_dataset(), report)["metrics"]
    assert recomputed["usageCoverage"] == 1.0
    assert recomputed["averageLatencyMs"] == 1
    assert recomputed["averageTokens"] == 0
    assert recomputed["estimatedCost"] == 0

    report["metrics"] = recomputed
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(report), encoding="utf-8")
    assert validate_baseline_report(load_dataset(), candidate) == 0
    report["metrics"]["estimatedCost"] = 1
    candidate.write_text(json.dumps(report), encoding="utf-8")
    assert validate_baseline_report(load_dataset(), candidate) == 1
