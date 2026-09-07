"""Offline validation of the AI golden test set (no network / no DeepSeek).

Ensures the regression dataset stays well-formed and only references tools that
actually exist in the registry. The full live scoring lives in
``scripts/ai_eval.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.ai.tools import TOOLS

DATASET = Path(__file__).resolve().parent / "golden_questions.json"
META = Path(__file__).resolve().parent / "golden_questions.meta.json"


def _load() -> list[dict]:
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    meta = json.loads(META.read_text(encoding="utf-8"))
    return [
        {
            **row,
            "schemaVersion": meta["schemaVersion"],
            "requiredTools": row.get("requiredTools", row.get("expectTools", [])),
            "allowedTools": row.get(
                "allowedTools", row.get("requiredTools", row.get("expectTools", []))
            ),
            "forbiddenTools": row.get("forbiddenTools", []),
            "source": meta["source"],
            "fixtureRef": meta["fixture"]["ref"],
            "asOf": meta["fixture"]["asOf"],
            "difficulty": meta["difficulty"],
            "failureClass": meta["failureClass"],
            "holdout": meta["holdout"],
            **meta.get("questionOverrides", {}).get(row["id"], {}),
        }
        for row in rows
    ]


def test_dataset_has_at_least_30_questions():
    assert len(_load()) >= 30


def test_ids_are_unique():
    ids = [q["id"] for q in _load()]
    assert len(ids) == len(set(ids))


def test_frozen_fixture_checksums_match():
    meta = json.loads(META.read_text(encoding="utf-8"))
    fixture = meta["fixture"]
    builder = DATASET.parent.parent / "scripts" / "seed_ci_market.py"
    tool_results = DATASET.parent.parent / fixture["toolResultsPath"]
    assert hashlib.sha256(DATASET.read_bytes()).hexdigest() == fixture[
        "questionsSha256"
    ]
    assert hashlib.sha256(builder.read_bytes()).hexdigest() == fixture[
        "builderSha256"
    ]
    assert hashlib.sha256(tool_results.read_bytes()).hexdigest() == fixture[
        "toolResultsSha256"
    ]


def test_required_fields_present():
    for q in _load():
        assert q.get("id")
        assert q.get("category")
        assert q.get("question")
        for key in (
            "schemaVersion",
            "requiredTools",
            "allowedTools",
            "forbiddenTools",
            "source",
            "fixtureRef",
            "asOf",
            "difficulty",
            "failureClass",
        ):
            assert key in q
        assert q["holdout"] is True
        if q["requiredTools"]:
            assert set(q["requiredTools"]) <= set(q["expectedToolArguments"])
        if q.get("expectNumericFrom"):
            assert q.get("expectedFacts")


def test_expected_tools_exist():
    valid = {t["function"]["name"] for t in TOOLS}
    for q in _load():
        for tool in (
            q["requiredTools"] + q["allowedTools"] + q["forbiddenTools"]
        ):
            assert tool in valid, f"{q['id']} 引用了未知工具 {tool}"


_NUMERIC_SOURCES = {
    "get_quotes",
    "get_market_overview",
    "get_financials",
    "get_capital_flow",
}


def test_expect_numeric_from_is_valid():
    for q in _load():
        source = q.get("expectNumericFrom")
        if source is None:
            continue
        assert source in _NUMERIC_SOURCES, f"{q['id']} 非法 expectNumericFrom={source}"


def test_covers_core_categories():
    cats = {q["category"] for q in _load()}
    for required in ["大盘指数", "报价", "K线", "财务摘要", "资金流", "选股", "合规", "回测"]:
        assert required in cats, f"缺少分类：{required}"
