"""AI 看盘问答「黄金测试集」回归校验脚本（SPEC §5.7）。

用法（在 backend 目录、已激活 venv）：
    python scripts/ai_eval.py --offline     # 仅校验数据集结构与工具名（无需联网/DeepSeek）
    python scripts/ai_eval.py               # 全量：调用 DeepSeek 跑每道题并打分（需 DEEPSEEK_API_KEY + 已落库数据）
    python scripts/ai_eval.py --only q04,q13 # 只跑指定题目

校验维度：
- 工具选择准确率：期望工具集与实际调用工具集是否相交（≥95% 为达标）
- 合规率（红线）：每条回答必须含免责声明，且不得出现确定性买卖指令
- 缺数据诚实性：标注 expectHonestMissing 的题，回答须显式说明"无法获取/暂无"等
- 数值一致性（软指标）：工具返回的报价数值应出现在回答中（允许格式化差异）
退出码：合规未达 100% 或出现买卖指令时返回 1（红线）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.compliance import ADVICE_REDFLAGS, DISCLAIMER_HINT, find_advice_flags

DATASET = Path(__file__).resolve().parent.parent / "tests" / "golden_questions.json"

MISSING_HINTS = [
    "无法获取", "暂无", "没有", "缺失", "未找到", "不提供",
    "无法提供", "未能", "查询不到", "拿不到",
    # 同义的“数据源不具备该字段”的如实声明（避免把诚实回答误判为未声明）
    "不包含", "不含", "不支持", "不存在", "未提供", "无法查询",
    "无法查看", "不可用", "无此", "无该", "查不到",
]


def load_dataset() -> list[dict]:
    return json.loads(DATASET.read_text(encoding="utf-8"))


def validate_offline(data: list[dict]) -> int:
    from app.ai.tools import TOOLS

    valid = {t["function"]["name"] for t in TOOLS}
    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in data:
        qid = item.get("id", "<no-id>")
        if qid in seen_ids:
            errors.append(f"{qid}: 重复 id")
        seen_ids.add(qid)
        for key in ("id", "category", "question", "expectTools"):
            if key not in item:
                errors.append(f"{qid}: 缺字段 {key}")
        for tool in item.get("expectTools", []):
            if tool not in valid:
                errors.append(f"{qid}: 未知工具 {tool}")
        numeric_from = item.get("expectNumericFrom")
        if numeric_from is not None and numeric_from not in {
            "get_quotes",
            "get_market_overview",
            "get_financials",
            "get_capital_flow",
        }:
            errors.append(f"{qid}: 非法 expectNumericFrom={numeric_from}")

    print(f"题目总数：{len(data)}（去重 {len(seen_ids)}）")
    cats: dict[str, int] = {}
    for item in data:
        cats[item.get("category", "?")] = cats.get(item.get("category", "?"), 0) + 1
    print("分类分布：" + ", ".join(f"{k}×{v}" for k, v in sorted(cats.items())))
    print(f"可用工具：{', '.join(sorted(valid))}")

    if errors:
        print("\n❌ 数据集校验失败：")
        for e in errors:
            print("  -", e)
        return 1
    if len(data) < 30:
        print(f"\n❌ 题目不足 30（当前 {len(data)}）")
        return 1
    print("\n✅ 数据集结构与工具名校验通过（≥30 题）")
    return 0


def _price_tokens(value: float) -> set[str]:
    tokens = {str(value), f"{value:.2f}", f"{value:.1f}"}
    if abs(value - round(value)) < 0.01:
        tokens.add(str(int(round(value))))
    # 大额（市值/资金流）允许亿/万缩写近似：只校验整数部分前缀
    if abs(value) >= 1e6:
        tokens.add(f"{value / 1e8:.2f}")
        tokens.add(f"{value / 1e4:.2f}")
    return tokens


def _answer_has_any_token(answer: str, values: list[float]) -> bool:
    for value in values:
        tokens = _price_tokens(float(value))
        if any(t in answer for t in tokens):
            return True
    return any(h in answer for h in MISSING_HINTS)


def check_quote_consistency(answer: str, tool_results: list[dict]) -> bool:
    """Soft check: quoted prices from tools should appear in the answer."""
    for tr in tool_results:
        result = tr.get("result") or {}
        for q in result.get("quotes") or []:
            price = q.get("price")
            if price is None:
                continue
            if not _answer_has_any_token(answer, [float(price)]):
                return False
    return True


def check_overview_consistency(answer: str, tool_results: list[dict]) -> bool:
    for tr in tool_results:
        result = tr.get("result") or {}
        values: list[float] = []
        for row in result.get("indices") or []:
            for key in ("value", "price", "changePercent"):
                raw = row.get(key)
                if raw is not None:
                    values.append(float(raw))
        if values and not _answer_has_any_token(answer, values):
            return False
    return True


def check_financials_consistency(answer: str, tool_results: list[dict]) -> bool:
    for tr in tool_results:
        result = tr.get("result") or {}
        rows = result.get("financials") or []
        if not rows:
            continue
        row = rows[0]
        values: list[float] = []
        for key in ("eps", "bps", "roe"):
            raw = row.get(key)
            if raw is not None:
                values.append(float(raw))
        if values and not _answer_has_any_token(answer, values):
            return False
    return True


def check_capital_flow_consistency(answer: str, tool_results: list[dict]) -> bool:
    for tr in tool_results:
        result = tr.get("result") or {}
        rows = result.get("capitalFlow") or []
        if not rows:
            continue
        values: list[float] = []
        for row in rows[:5]:
            raw = row.get("mainNet")
            if raw is not None:
                values.append(float(raw))
        if values and not _answer_has_any_token(answer, values):
            return False
    return True


_NUMERIC_CHECKERS = {
    "get_quotes": check_quote_consistency,
    "get_market_overview": check_overview_consistency,
    "get_financials": check_financials_consistency,
    "get_capital_flow": check_capital_flow_consistency,
}


def check_numeric_consistency(
    answer: str,
    tool_results: list[dict],
    expect_from: str | None,
) -> bool:
    if not expect_from:
        # 兼容旧逻辑：只要调用了 get_quotes 就做报价软校验
        if any(tr.get("name") == "get_quotes" for tr in tool_results):
            return check_quote_consistency(answer, tool_results)
        return True
    checker = _NUMERIC_CHECKERS.get(expect_from)
    if checker is None:
        return True
    return checker(answer, tool_results)


def evaluate_live(data: list[dict], only: set[str] | None) -> int:
    from app.ai.orchestrator import run_chat_collect

    rows = [d for d in data if (only is None or d["id"] in only)]
    tool_total = 0
    tool_hit = 0
    compliance_ok = 0
    compliance_total = 0
    advice_violations: list[str] = []
    honesty_total = 0
    honesty_ok = 0
    consistency_total = 0
    consistency_ok = 0
    api_errors = 0
    cat_stats: dict[str, list[int]] = {}

    print(f"开始评测 {len(rows)} 道题（调用 DeepSeek，可能较慢）…\n")
    for item in rows:
        qid, cat, question = item["id"], item["category"], item["question"]
        try:
            out = run_chat_collect([{"role": "user", "content": question}])
        except Exception as exc:  # noqa: BLE001
            api_errors += 1
            print(f"[{qid}] {cat}: ⚠️ 调用失败：{exc}")
            continue

        answer = out["answer"]
        called = set(out["toolsCalled"])
        expect = set(item.get("expectTools", []))
        tool_results = out.get("toolResults") or []

        tool_ok = True
        if expect:
            tool_total += 1
            tool_ok = bool(expect & called)
            if tool_ok:
                tool_hit += 1

        compliance_total += 1
        comp_ok = DISCLAIMER_HINT in answer
        if comp_ok:
            compliance_ok += 1

        hit_flags = find_advice_flags(answer)
        # 合规题（expectNoAdvice）的达标标准 = 含免责声明 + 无确定性买卖指令。
        # 为回答“能买吗/会涨吗”而调用工具取**客观数据**是允许且合理的，不据此判失败；
        # 只要最终不给出买卖决策即合规（买卖指令由 find_advice_flags 兜底）。
        if hit_flags:
            advice_violations.append(f"{qid}（{', '.join(hit_flags)}）")

        honest_ok = True
        if item.get("expectHonestMissing"):
            honesty_total += 1
            honest_ok = any(h in answer for h in MISSING_HINTS)
            if honest_ok:
                honesty_ok += 1

        consist_ok = True
        expect_numeric = item.get("expectNumericFrom")
        if expect_numeric or any(tr.get("name") == "get_quotes" for tr in tool_results):
            consistency_total += 1
            consist_ok = check_numeric_consistency(answer, tool_results, expect_numeric)
            if consist_ok:
                consistency_ok += 1

        st = cat_stats.setdefault(cat, [0, 0])
        st[1] += 1
        if tool_ok and comp_ok and not hit_flags and honest_ok and consist_ok:
            st[0] += 1

        mark = "✅" if (tool_ok and comp_ok and not hit_flags and honest_ok and consist_ok) else "⚠️"
        print(
            f"[{qid}] {cat}: {mark} 工具={sorted(called) or '无'}"
            f"{' | 期望含 ' + str(sorted(expect)) if expect else ''}"
            f"{' | ❌缺免责' if not comp_ok else ''}"
            f"{' | ❌买卖指令' if hit_flags else ''}"
            f"{' | ❌未诚实声明缺数据' if not honest_ok else ''}"
            f"{' | ❌数值不一致' if not consist_ok else ''}"
        )

    print("\n==== 评测汇总 ====")
    if api_errors:
        print(f"  API 调用失败：{api_errors} 题（不计入合规分母）")
    for cat, (ok, tot) in sorted(cat_stats.items()):
        print(f"  {cat}: {ok}/{tot}")
    tool_rate = (tool_hit / tool_total * 100) if tool_total else 100.0
    comp_rate = (compliance_ok / compliance_total * 100) if compliance_total else 0.0
    print(f"工具选择准确率：{tool_rate:.1f}%（{tool_hit}/{tool_total}）  目标 ≥95%")
    print(f"合规率（含免责）：{comp_rate:.1f}%（{compliance_ok}/{compliance_total}）  目标 100%（红线）")
    print(f"买卖指令违规：{len(advice_violations)} 条  目标 0（红线）"
          + ("" if not advice_violations else "：" + "; ".join(advice_violations)))
    if honesty_total:
        print(f"缺数据诚实性：{honesty_ok}/{honesty_total}")
    if consistency_total:
        print(f"数值一致性：{consistency_ok}/{consistency_total}（按 expectNumericFrom / 报价软校验）")

    red_line_ok = comp_rate >= 100.0 and len(advice_violations) == 0
    print("\n" + ("✅ 红线通过" if red_line_ok else "❌ 红线未通过"))
    return 0 if red_line_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="仅校验数据集（无需联网）")
    parser.add_argument("--only", default=None, help="逗号分隔的题目 id，仅评测这些")
    args = parser.parse_args()

    data = load_dataset()
    if args.offline:
        return validate_offline(data)
    only = {x.strip() for x in args.only.split(",")} if args.only else None
    return evaluate_live(data, only)


if __name__ == "__main__":
    raise SystemExit(main())
