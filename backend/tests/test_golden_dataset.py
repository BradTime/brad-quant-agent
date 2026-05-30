"""Offline validation of the AI golden test set (no network / no DeepSeek).

Ensures the regression dataset stays well-formed and only references tools that
actually exist in the registry. The full live scoring lives in
``scripts/ai_eval.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ai.tools import TOOLS

DATASET = Path(__file__).resolve().parent / "golden_questions.json"


def _load() -> list[dict]:
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_dataset_has_at_least_30_questions():
    assert len(_load()) >= 30


def test_ids_are_unique():
    ids = [q["id"] for q in _load()]
    assert len(ids) == len(set(ids))


def test_required_fields_present():
    for q in _load():
        assert q.get("id")
        assert q.get("category")
        assert q.get("question")
        assert "expectTools" in q


def test_expected_tools_exist():
    valid = {t["function"]["name"] for t in TOOLS}
    for q in _load():
        for tool in q["expectTools"]:
            assert tool in valid, f"{q['id']} 引用了未知工具 {tool}"


def test_covers_core_categories():
    cats = {q["category"] for q in _load()}
    for required in ["大盘指数", "报价", "K线", "财务摘要", "资金流", "选股", "合规"]:
        assert required in cats, f"缺少分类：{required}"
