from scripts.analyze_ai_eval import analyze


def test_analyzer_buckets_tool_and_grounding_failures():
    result = analyze(
        {
            "results": [
                {"id": "ok", "ok": True},
                {
                    "id": "bad",
                    "ok": False,
                    "toolScore": {
                        "missing": ["get_quotes"],
                        "argumentErrors": ["get_financials"],
                    },
                    "numericConsistency": False,
                },
            ]
        }
    )
    assert result["passed"] == 1
    assert result["failedIds"] == ["bad"]
    assert result["buckets"] == {
        "argument_errors": 1,
        "grounding": 1,
        "missing_tools": 1,
    }
    assert result["affectedTools"] == {
        "get_quotes": 1,
        "get_financials": 1,
    }
