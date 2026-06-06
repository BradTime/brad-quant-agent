"""自主深度研究（多轮规划编排）—— Phase 2 「对话中枢/自主 Agent」增量。

与 `/ai` 的单问反应式 ReAct 不同，这里是**显式三段编排**：
1. 规划者把研究问题拆成 2-4 个可由工具求证的子问题；
2. 逐个子问题跑工具调用 ReAct（复用 `orchestrator.run_chat_collect`）取真实数据；
3. 主笔综合各子发现成一份结构化深度研究报告（`run_completion_stream`，附合规免责）。

全程 SSE 流式产出：``{"step":..}`` 进度 / ``{"plan":[..]}`` 研究计划 / ``{"delta":..}`` 报告正文。
复用同一工具能力层与合规守卫；任何子步失败均降级、不中断整体。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator

from app.ai.deepseek import get_client
from app.ai.orchestrator import run_chat_collect, run_completion_stream
from app.ai.prompts import RESEARCH_PLANNER_PROMPT, RESEARCH_SYNTHESIS_PROMPT
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_SUBQUESTIONS = 4


def _parse_list(raw: str) -> list[str]:
    """稳健解析规划输出的 JSON 字符串数组（去 ```fence、抽首个 [...]）。"""
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(json)?", "", txt).strip()
        txt = re.sub(r"```$", "", txt).strip()
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        txt = m.group(0)
    try:
        arr = json.loads(txt)
    except (ValueError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    return [str(x).strip() for x in arr if str(x).strip()]


def _plan(question: str, context_hint: str = "") -> list[str]:
    """调用规划者拆解子问题；失败/空则降级为单步（原问题本身）。"""
    user = question if not context_hint else f"{context_hint}\n\n研究问题：{question}"
    try:
        completion = get_client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": RESEARCH_PLANNER_PROMPT},
                {"role": "user", "content": user},
            ],
            stream=False,
        )
        raw = completion.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("研究规划失败，降级为单步：%s", exc)
        return [question]
    subs = _parse_list(raw)
    return subs[:MAX_SUBQUESTIONS] or [question]


def _assemble(question: str, findings: list[tuple[str, str, list[str]]]) -> str:
    parts = [f"【原始研究问题】\n{question}\n", "【调研发现】"]
    for i, (subq, ans, tools) in enumerate(findings, 1):
        tag = f"（用到工具：{', '.join(tools)}）" if tools else "（未调用工具）"
        parts.append(f"\n## 子问题{i}：{subq} {tag}\n{ans or '（无有效发现）'}")
    parts.append("\n请据以上调研发现综合成最终深度研究报告。")
    return "\n".join(parts)


def stream_deep_research(question: str, context_hint: str = "") -> Iterator[dict]:
    """流式产出研究编排事件：step（进度）/ plan（研究计划）/ delta（报告）/ error。"""
    question = (question or "").strip()
    if not question:
        yield {"delta": "请提供研究问题。"}
        return

    yield {"step": "规划研究路径", "node": "planner"}
    plan = _plan(question, context_hint)
    yield {"plan": plan}

    findings: list[tuple[str, str, list[str]]] = []
    total = len(plan)
    for i, subq in enumerate(plan, 1):
        try:
            res = run_chat_collect([{"role": "user", "content": subq}], enforce=False)
            answer = res.get("answer", "")
            tools = res.get("toolsCalled") or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("子问题调研失败：%s", exc)
            answer, tools = f"（该子问题调研失败：{exc}）", []
        findings.append((subq, answer, tools))
        yield {"step": f"完成 {i}/{total}：{subq}", "node": "research", "tools": tools or None}

    yield {"step": "综合成稿", "node": "synth"}
    assembled = _assemble(question, findings)
    try:
        for piece in run_completion_stream(RESEARCH_SYNTHESIS_PROMPT, assembled):
            yield {"delta": piece}
    except Exception as exc:  # noqa: BLE001
        logger.warning("研究成稿失败：%s", exc)
        yield {"delta": f"\n\n⚠️ 研究成稿出错：{exc}"}
