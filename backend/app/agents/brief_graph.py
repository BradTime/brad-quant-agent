"""盘前早报多智能体状态图（LangGraph）。

拓扑：规划者 → [市场结构 / 资金面 / 消息面(RAG·可调工具) / 海外宏观] 四分析师并行 →
主编汇总 → 质量评审官（evaluator）→（不达标且未修订过则）主编修订（optimizer）→ 再评审
→ 合规反思（代码化红线校验）。即一个**有界（最多 1 轮）的 evaluator-optimizer 反思回环**。
- 每个节点把 {node, ms, chars, ...} 追加到 ``trace``（并行节点用 add reducer 合并），内置可观测。
- 消息面分析师可**按需调用 search_knowledge(RAG) 工具**补充背景（有界 1 轮）。
- ``stream_steps`` 以 LangGraph updates 流产出逐步进度事件 + 最终早报，供 SSE 实时展示。
- ``run_collect`` 一次性跑完（供调度器/脚本）。
LangSmith 追踪在配置了 key 时自动开启（见 llm.maybe_enable_langsmith）。
"""

from __future__ import annotations

import json
import logging
import operator
import re
import time
from typing import Annotated

from typing_extensions import TypedDict

from app.agents import prompts
from app.agents.llm import get_chat_model
from app.core.config import settings

logger = logging.getLogger(__name__)

_LABELS = {
    "planner": "规划",
    "market": "市场结构分析",
    "capital": "资金面分析",
    "news": "消息面分析(RAG)",
    "macro": "海外宏观分析",
    "editor": "主编汇总",
    "evaluator": "质量自评",
    "editor_revise": "主编修订",
    "reviewer": "合规审查",
}

# 反思回环修订轮数上限（防失控）；实际轮数取 min(settings.brief_max_revisions, 此上限)
_REVISION_CAP = 3

# 各分析师可按需调用的工具（节点→工具名白名单）；复用 ai.tools 能力层、有界 1 轮。
# 仅暴露与分析域相关、且以落库/已加超时降级为主的工具，沿用「早报不阻塞实时」的设计。
_NODE_TOOLS: dict[str, list[str]] = {
    "market": ["get_market_overview", "get_kline"],
    "capital": ["get_capital_flow", "get_dragon_tiger"],
    "news": ["search_knowledge", "get_news"],
}


def _max_revisions() -> int:
    return max(0, min(settings.brief_max_revisions, _REVISION_CAP))


def _node_tools(node: str) -> list[dict]:
    from app.ai.tools import TOOLS

    names = set(_NODE_TOOLS.get(node, []))
    return [t for t in TOOLS if t.get("function", {}).get("name") in names]


class BriefState(TypedDict, total=False):
    data_text: str
    planner: str
    market: str
    capital: str
    news: str
    macro: str
    draft: str
    final: str
    review: dict
    revisions: int
    trace: Annotated[list[dict], operator.add]


def is_available() -> bool:
    try:
        import langchain_openai  # noqa: F401
        import langgraph  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _trace(node: str, start: float, text: str, **extra) -> dict:
    """统一节点轨迹：含耗时 ms + 起止 epoch ms（start/end），供前端时序甘特图展示并行重叠。"""
    end = time.time()
    tr = {
        "node": node,
        "label": _LABELS.get(node, node),
        "ms": int((end - start) * 1000),
        "start": int(start * 1000),
        "end": int(end * 1000),
        "chars": len(text),
    }
    tr.update({k: v for k, v in extra.items() if v is not None})
    return tr


def _invoke(node: str, system_prompt: str, human: str, temperature: float = 0.3) -> tuple[str, dict]:
    from langchain_core.messages import HumanMessage, SystemMessage

    start = time.time()
    model = get_chat_model(temperature)
    resp = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    return text, _trace(node, start, text)


def _invoke_with_tools(
    node: str,
    system_prompt: str,
    human: str,
    tool_specs: list[dict],
    temperature: float = 0.3,
    max_rounds: int = 1,
) -> tuple[str, dict]:
    """带**有界**工具调用的节点调用：模型可申请工具→本地执行→回灌→再生成。

    与在线问答共用同一 ``app.ai.tools.execute_tool`` 能力层；最多 ``max_rounds`` 轮，防止环路/超额。
    """
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    from app.ai.tools import execute_tool

    start = time.time()
    model = get_chat_model(temperature).bind_tools(tool_specs)
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=human)]
    used: list[str] = []
    resp = model.invoke(messages)
    rounds = 0
    while getattr(resp, "tool_calls", None) and rounds < max_rounds:
        messages.append(resp)
        for tc in resp.tool_calls:
            name = tc.get("name", "")
            args = tc.get("args") or {}
            try:
                result = execute_tool(name, args)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            used.append(name)
            payload = json.dumps(result, ensure_ascii=False, default=str)[:4000]
            messages.append(ToolMessage(content=payload, tool_call_id=tc.get("id", "")))
        resp = model.invoke(messages)
        rounds += 1
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    # 收尾：若达到工具轮上限后模型仍未给文字结论（content 为空/仍想调工具），
    # 用不带工具的模型强制基于已得结果产出文字，避免该分析段为空。
    if not text.strip() and used:
        from langchain_core.messages import HumanMessage

        messages.append(
            HumanMessage(content="请基于以上工具返回结果，直接输出文字分析结论，不要再调用工具。")
        )
        resp2 = get_chat_model(temperature).invoke(messages)
        text = resp2.content if isinstance(resp2.content, str) else str(resp2.content)
    return text, _trace(node, start, text, tools=used or None)


# ---------- 节点 ----------


def _analyst(node: str, system_prompt: str, state: BriefState) -> tuple[str, dict]:
    """分析师统一入口：有白名单工具则按需调用（有界 1 轮），否则纯文本生成。"""
    specs = _node_tools(node)
    if specs:
        return _invoke_with_tools(node, system_prompt, state["data_text"], specs, max_rounds=1)
    return _invoke(node, system_prompt, state["data_text"])


def _planner(state: BriefState) -> dict:
    text, tr = _invoke("planner", prompts.PLANNER_PROMPT, state["data_text"])
    return {"planner": text, "trace": [tr]}


def _market(state: BriefState) -> dict:
    text, tr = _analyst("market", prompts.MARKET_ANALYST_PROMPT, state)
    return {"market": text, "trace": [tr]}


def _capital(state: BriefState) -> dict:
    text, tr = _analyst("capital", prompts.CAPITAL_ANALYST_PROMPT, state)
    return {"capital": text, "trace": [tr]}


def _news(state: BriefState) -> dict:
    text, tr = _analyst("news", prompts.NEWS_ANALYST_PROMPT, state)
    return {"news": text, "trace": [tr]}


def _macro(state: BriefState) -> dict:
    text, tr = _invoke("macro", prompts.MACRO_ANALYST_PROMPT, state["data_text"])
    return {"macro": text, "trace": [tr]}


def _editor(state: BriefState) -> dict:
    human = (
        f"【数据包】\n{state['data_text']}\n\n"
        f"【规划要点】\n{state.get('planner','')}\n\n"
        f"【市场结构分析】\n{state.get('market','')}\n\n"
        f"【资金面分析】\n{state.get('capital','')}\n\n"
        f"【消息面分析】\n{state.get('news','')}\n\n"
        f"【海外宏观分析】\n{state.get('macro','')}\n\n"
        "请据此整合成最终盘前早报。"
    )
    text, tr = _invoke("editor", prompts.EDITOR_PROMPT, human, temperature=0.4)
    return {"draft": text, "trace": [tr]}


def _parse_review(raw: str) -> dict:
    """稳健解析评审 JSON：去 ```fence、抽首个 {...}、按规则兜底 pass。解析失败不阻断（pass=True）。"""
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(json)?", "", txt).strip()
        txt = re.sub(r"```$", "", txt).strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        txt = m.group(0)
    try:
        rep = json.loads(txt)
        if not isinstance(rep, dict):
            raise ValueError("review not a dict")
    except (ValueError, TypeError):
        return {"pass": True, "parseError": True, "issues": [], "scores": {}}
    scores = rep.get("scores") or {}
    try:
        total = sum(float(v) for v in scores.values())
    except (ValueError, TypeError):
        total = None
    rep["total"] = total
    crit = [scores.get("grounding"), scores.get("honesty"), scores.get("conditional")]
    rule_fail = any(isinstance(c, (int, float)) and c < 4 for c in crit) or (
        total is not None and total < 18
    )
    rep["pass"] = bool(rep.get("pass", not rule_fail)) and not rule_fail
    return rep


def _evaluator(state: BriefState) -> dict:
    """质量评审官：对主编草稿做 JSON 化自评打分（不重写正文），输出落入 trace 供观测。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    start = time.time()
    human = (
        f"【数据包】\n{state['data_text']}\n\n【主编草稿】\n{state.get('draft','')}\n\n"
        "请严格按规则只输出 JSON 评审结果。"
    )
    model = get_chat_model(0.0)
    resp = model.invoke([SystemMessage(content=prompts.EVALUATOR_PROMPT), HumanMessage(content=human)])
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    report = _parse_review(raw)
    tr = _trace(
        "evaluator",
        start,
        raw,
        **{
            "pass": report.get("pass"),
            "scores": report.get("scores"),
            "total": report.get("total"),
            "issues": report.get("issues") or [],
        },
    )
    return {"review": report, "trace": [tr]}


def _editor_revise(state: BriefState) -> dict:
    """优化器：依据评审反馈对草稿做最小必要修订，回到评审再判一次（有界）。"""
    report = state.get("review") or {}
    feedback = (
        f"待修订问题：{report.get('issues') or '无'}\n"
        f"修订建议：{report.get('suggestions', '') or '提升结构完整性与可执行边界'}"
    )
    human = (
        f"【数据包】\n{state['data_text']}\n\n【上一版草稿】\n{state.get('draft','')}\n\n"
        f"【评审反馈】\n{feedback}\n\n请输出修订后的完整早报正文。"
    )
    text, tr = _invoke("editor_revise", prompts.EDITOR_REVISE_PROMPT, human, temperature=0.3)
    return {"draft": text, "revisions": state.get("revisions", 0) + 1, "trace": [tr]}


def _route_after_review(state: BriefState) -> str:
    report = state.get("review") or {}
    if not report.get("pass", True) and state.get("revisions", 0) < _max_revisions():
        return "revise"
    return "done"


def _reviewer(state: BriefState) -> dict:
    """代码化合规反思：确保免责声明、拦截确定性买卖指令（不依赖额外 LLM 调用，确定性强）。"""
    from app.ai.compliance import enforce_compliance, find_advice_flags

    start = time.time()
    draft = state.get("draft", "")
    flags = find_advice_flags(draft)
    final = enforce_compliance(draft)
    note = "通过" if not flags else f"拦截买卖指令:{flags}"
    return {"final": final, "trace": [_trace("reviewer", start, final, note=note)]}


_compiled = None


def get_graph():
    global _compiled
    if _compiled is not None:
        return _compiled
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(BriefState)
    g.add_node("planner", _planner)
    g.add_node("market", _market)
    g.add_node("capital", _capital)
    g.add_node("news", _news)
    g.add_node("macro", _macro)
    g.add_node("editor", _editor)
    g.add_node("evaluator", _evaluator)
    g.add_node("editor_revise", _editor_revise)
    g.add_node("reviewer", _reviewer)
    g.add_edge(START, "planner")
    g.add_edge("planner", "market")
    g.add_edge("planner", "capital")
    g.add_edge("planner", "news")
    g.add_edge("planner", "macro")
    g.add_edge("market", "editor")
    g.add_edge("capital", "editor")
    g.add_edge("news", "editor")
    g.add_edge("macro", "editor")
    g.add_edge("editor", "evaluator")
    # 有界 evaluator-optimizer 反思回环：评审不达标且未修订过 → 修订 → 再评审；否则 → 合规审查
    g.add_conditional_edges("evaluator", _route_after_review, {"revise": "editor_revise", "done": "reviewer"})
    g.add_edge("editor_revise", "evaluator")
    g.add_edge("reviewer", END)
    _compiled = g.compile()
    return _compiled


# ---------- 运行器 ----------


def run_collect(data_text: str) -> dict:
    """一次性跑完，返回 {final, trace}。"""
    state = get_graph().invoke({"data_text": data_text, "trace": []})
    return {"final": state.get("final", "") or state.get("draft", ""), "trace": state.get("trace", [])}


def stream_steps(data_text: str):
    """以 updates 流产出逐步进度，最后产出 final。

    产出 dict：``{"type":"step", node,label,ms}`` 或 ``{"type":"final", content, trace}``。
    """
    final_text = ""
    trace: list[dict] = []
    for update in get_graph().stream({"data_text": data_text, "trace": []}, stream_mode="updates"):
        for node, partial in update.items():
            if not isinstance(partial, dict):
                continue
            entry = (partial.get("trace") or [{}])[0]
            yield {
                "type": "step",
                "node": node,
                "label": entry.get("label", _LABELS.get(node, node)),
                "ms": entry.get("ms"),
            }
            if partial.get("final"):
                final_text = partial["final"]
            elif partial.get("draft") and not final_text:
                final_text = partial["draft"]
            if partial.get("trace"):
                trace.extend(partial["trace"])
    yield {"type": "final", "content": final_text, "trace": trace}
