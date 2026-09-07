"""Categorize failures in a machine-readable AI evaluation report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def analyze(report: dict[str, Any]) -> dict[str, Any]:
    buckets: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    failed: list[str] = []
    for row in report.get("results", []):
        if row.get("ok"):
            continue
        failed.append(str(row.get("id")))
        score = row.get("toolScore") or {}
        for key, bucket in (
            ("missing", "missing_tools"),
            ("unexpected", "unexpected_tools"),
            ("forbiddenCalled", "forbidden_tools"),
            ("argumentErrors", "argument_errors"),
        ):
            values = score.get(key) or []
            if values:
                buckets[bucket] += 1
                tools.update(map(str, values))
        if row.get("apiError"):
            buckets["api_errors"] += 1
        if not row.get("honesty", True):
            buckets["honesty"] += 1
        if not row.get("numericConsistency", True):
            buckets["grounding"] += 1
        if row.get("safeAdviceFlags") or row.get("rawAdviceFlags"):
            buckets["compliance"] += 1
    total = len(report.get("results", []))
    return {
        "total": total,
        "passed": total - len(failed),
        "failed": len(failed),
        "failedIds": failed,
        "buckets": dict(sorted(buckets.items())),
        "affectedTools": dict(tools.most_common()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    result = analyze(json.loads(args.report.read_text(encoding="utf-8")))
    print(
        f"评测 {result['total']} 题：通过 {result['passed']}，失败 {result['failed']}"
    )
    for name, count in result["buckets"].items():
        print(f"- {name}: {count}")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
