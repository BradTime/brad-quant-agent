"""盘前早报多智能体状态图（LangGraph）。

拓扑：规划者 → [市场结构 / 资金面 / 消息面(RAG)] 三分析师并行 → 主编汇总 → 合规反思。
- 每个节点把 {node, ms, chars} 追加到 ``trace``（并行节点用 add reducer 合并），实现内置可观测。
- ``stream_steps`` 以 LangGraph updates 流产出逐步进度事件 + 最终早报，供 SSE 实时展示。
- ``run_collect`` 一次性跑完（供调度器/脚本）。
LangSmith 追踪在配置了 key 时自动开启（见 llm.maybe_enable_langsmith）。
"""

from __future__ import annotations

import logging
import operator
import time
from typing import Annotated

from typing_extensions import TypedDict

from app.agents import prompts
from app.agents.llm import get_chat_model

logger = logging.getLogger(__name__)

_LABELS = {
    "planner": "规划",
    "market": "市场结构分析",
    "capital": "资金面分析",
    "news": "消息面分析(RAG)",
    "editor": "主编汇总",
    "reviewer": "合规审查",
}


class BriefState(TypedDict, total=False):
    data_text: str
    planner: str
    market: str
    capital: str
    news: str
    draft: str
    final: str
    trace: Annotated[list[dict], operator.add]


def is_available() -> bool:
    try:
        import langgraph  # noqa: F401
        import langchain_openai  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _invoke(node: str, system_prompt: str, human: str, temperature: float = 0.3) -> tuple[str, dict]:
    from langchain_core.messages import HumanMessage, SystemMessage

    t0 = time.monotonic()
    model = get_chat_model(temperature)
    resp = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human)])
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    ms = int((time.monotonic() - t0) * 1000)
    return text, {"node": node, "label": _LABELS.get(node, node), "ms": ms, "chars": len(text)}


# ---------- 节点 ----------


def _planner(state: BriefState) -> dict:
    text, tr = _invoke("planner", prompts.PLANNER_PROMPT, state["data_text"])
    return {"planner": text, "trace": [tr]}


def _market(state: BriefState) -> dict:
    text, tr = _invoke("market", prompts.MARKET_ANALYST_PROMPT, state["data_text"])
    return {"market": text, "trace": [tr]}


def _capital(state: BriefState) -> dict:
    text, tr = _invoke("capital", prompts.CAPITAL_ANALYST_PROMPT, state["data_text"])
    return {"capital": text, "trace": [tr]}


def _news(state: BriefState) -> dict:
    text, tr = _invoke("news", prompts.NEWS_ANALYST_PROMPT, state["data_text"])
    return {"news": text, "trace": [tr]}


def _editor(state: BriefState) -> dict:
    human = (
        f"【数据包】\n{state['data_text']}\n\n"
        f"【规划要点】\n{state.get('planner','')}\n\n"
        f"【市场结构分析】\n{state.get('market','')}\n\n"
        f"【资金面分析】\n{state.get('capital','')}\n\n"
        f"【消息面分析】\n{state.get('news','')}\n\n"
        "请据此整合成最终盘前早报。"
    )
    text, tr = _invoke("editor", prompts.EDITOR_PROMPT, human, temperature=0.4)
    return {"draft": text, "trace": [tr]}


def _reviewer(state: BriefState) -> dict:
    """代码化合规反思：确保免责声明、拦截确定性买卖指令（不依赖额外 LLM 调用，确定性强）。"""
    from app.ai.compliance import enforce_compliance, find_advice_flags

    t0 = time.monotonic()
    draft = state.get("draft", "")
    flags = find_advice_flags(draft)
    final = enforce_compliance(draft)
    ms = int((time.monotonic() - t0) * 1000)
    note = "通过" if not flags else f"拦截买卖指令:{flags}"
    return {
        "final": final,
        "trace": [{"node": "reviewer", "label": _LABELS["reviewer"], "ms": ms, "chars": len(final), "note": note}],
    }


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
    g.add_node("editor", _editor)
    g.add_node("reviewer", _reviewer)
    g.add_edge(START, "planner")
    g.add_edge("planner", "market")
    g.add_edge("planner", "capital")
    g.add_edge("planner", "news")
    g.add_edge("market", "editor")
    g.add_edge("capital", "editor")
    g.add_edge("news", "editor")
    g.add_edge("editor", "reviewer")
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
