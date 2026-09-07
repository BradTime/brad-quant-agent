"""Function-calling orchestration with streaming.

Runs up to ``MAX_TOOL_ROUNDS`` rounds: stream the model's output, accumulate any
tool-call deltas, execute the tools, feed results back, and continue until the
model produces a final text answer. User-facing text is yielded as it streams.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from app.ai.compliance import (
    ADVICE_REDFLAGS,
    ADVICE_REPLACEMENT,
    enforce_compliance,
    find_advice_flags,
    stream_compliance_tail,
)
from app.ai.deepseek import get_client
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.tools import TOOLS, execute_tool
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_ROUNDS_NOTE = "\n（已达到最大工具调用轮数。）"
_SAFE_STREAM_CHUNK_SIZE = 256
_FINAL_ANSWER_TOOL = "respond_without_tools"
_ROUTER_POLICY = (
    "优先选择满足用户问题所需的最小工具集合。不得猜测代码、日期或工具参数；"
    "上下文足够时调用 respond_without_tools。"
)
_FINAL_ANSWER_POLICY = (
    "仅基于已返回的工具结果回答；明确区分缺数据、工具失败与零值，"
    "不得补造数值、来源或时点。"
)
_ROUTER_TOOLS = [
    *TOOLS,
    {
        "type": "function",
        "function": {
            "name": _FINAL_ANSWER_TOOL,
            "description": (
                "当现有上下文已足够回答、无需调用更多数据工具时调用。"
                "这是路由哨兵，不要在 content 中生成最终答案。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


@dataclass
class ChatRunTrace:
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    exhausted: bool = False


def _build_messages(user_messages: list[dict]) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, *user_messages]


def _yield_safe_chunks(text: str) -> Iterator[str]:
    safe = enforce_compliance(text)
    for start in range(0, len(safe), _SAFE_STREAM_CHUNK_SIZE):
        yield safe[start : start + _SAFE_STREAM_CHUNK_SIZE]


def _guarded_model_stream(stream) -> Iterator[str]:
    """Stream no-tool model text while retaining enough tail to block red flags."""
    hold = max(map(len, ADVICE_REDFLAGS)) - 1
    buffer = ""
    emitted: list[str] = []
    blocked = False
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            piece = getattr(chunk.choices[0].delta, "content", None)
            if not piece:
                continue
            buffer += piece
            if find_advice_flags(buffer):
                blocked = True
                break
            if len(buffer) > hold:
                safe = buffer[:-hold]
                buffer = buffer[-hold:]
                emitted.append(safe)
                yield safe
    finally:
        if hasattr(stream, "close"):
            stream.close()

    if not blocked and not emitted and not buffer:
        yield from _yield_safe_chunks("")
        return
    if blocked:
        emitted.append(ADVICE_REPLACEMENT)
        yield ADVICE_REPLACEMENT
    elif buffer:
        emitted.append(buffer)
        yield buffer
    tail = stream_compliance_tail("".join(emitted))
    if tail:
        yield tail


def _append_tool_results(
    messages: list[dict],
    assistant_content: str | None,
    calls,
    tool_executor=None,
    routing_text: str = "",
) -> tuple[list[str], list[dict]]:
    tools_called: list[str] = []
    tool_results: list[dict] = []
    executor = tool_executor or execute_tool

    messages.append(
        {
            "role": "assistant",
            "content": assistant_content or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in calls
            ],
        }
    )
    for c in calls:
        name = c.function.name
        tools_called.append(name)
        argument_error: str | None = None
        try:
            args = json.loads(c.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
            argument_error = "工具参数不是有效 JSON"
        if argument_error:
            result = {"error": argument_error}
        else:
            try:
                from app.ai.router import repair_tool_arguments

                args = repair_tool_arguments(name, args, user_text=routing_text)
                result = executor(name, args)
            except Exception as exc:  # noqa: BLE001
                logger.warning("工具 %s 执行失败: %s", name, exc)
                result = {"error": f"工具执行失败: {exc}"}
        tool_results.append({"name": name, "args": args, "result": result})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": c.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            }
        )
    return tools_called, tool_results


def _usage(completion) -> dict[str, int]:
    usage = getattr(completion, "usage", None)
    return {
        "promptTokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completionTokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def _route_tools(
    client, messages: list[dict], tool_executor=None
) -> tuple[list[str], list[dict], bool, dict[str, int]]:
    """Run bounded required-tool routing shared by live and evaluation paths."""
    tools_called: list[str] = []
    tool_results: list[dict] = []
    usage = {"promptTokens": 0, "completionTokens": 0}
    from app.ai.router import route_deterministically

    latest_user = next(
        (
            str(message.get("content", ""))
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    deterministic = route_deterministically(latest_user)
    if deterministic is not None:
        if not deterministic.calls:
            return tools_called, tool_results, False, usage
        calls = [
            SimpleNamespace(
                id=f"deterministic-{index}",
                function=SimpleNamespace(
                    name=call.name,
                    arguments=json.dumps(call.arguments, ensure_ascii=False),
                ),
            )
            for index, call in enumerate(deterministic.calls)
        ]
        called, results = _append_tool_results(
            messages,
            None,
            calls,
            tool_executor=tool_executor,
            routing_text=latest_user,
        )
        return called, results, False, usage

    messages.append({"role": "system", "content": _ROUTER_POLICY})
    for _ in range(MAX_TOOL_ROUNDS):
        completion = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            tools=_ROUTER_TOOLS,
            tool_choice="required",
            stream=False,
        )
        response_usage = _usage(completion)
        usage = {
            key: usage[key] + response_usage[key]
            for key in usage
        }
        msg = completion.choices[0].message
        calls = [
            call
            for call in (getattr(msg, "tool_calls", None) or [])
            if call.function.name != _FINAL_ANSWER_TOOL
        ]
        if not calls:
            return tools_called, tool_results, False, usage
        called, results = _append_tool_results(
            messages,
            None,
            calls,
            tool_executor=tool_executor,
            routing_text=latest_user,
        )
        tools_called.extend(called)
        tool_results.extend(results)
    return tools_called, tool_results, True, usage


def run_completion_stream(system_prompt: str, user_content: str) -> Iterator[str]:
    """Single-shot generation (no tools) for pre-assembled-context tasks like the
    morning brief. Buffers model text so compliance is enforced before emission."""
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    stream = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=True,
    )
    yield from _guarded_model_stream(stream)


def run_chat_collect(
    user_messages: list[dict],
    enforce: bool = True,
    *,
    tool_executor=None,
) -> dict:
    """Non-streaming variant for evaluation/regression.

    ``enforce=False`` skips the compliance final pass — used by the deep-research
    orchestrator for intermediate sub-steps (the final synthesis enforces once),
    avoiding a disclaimer appended to every sub-finding.
    """
    answer = ""
    tools_called: list[str] = []
    tool_results: list[dict] = []

    latest_user = next(
        (
            str(message.get("content", ""))
            for message in reversed(user_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    from app.ai.router import (
        deterministic_direct_response,
        deterministic_evidence_summary,
        deterministic_tool_answer,
    )

    direct = deterministic_direct_response(latest_user)
    if direct is not None:
        return {
            "answer": enforce_compliance(direct) if enforce else direct,
            "toolsCalled": [],
            "toolResults": [],
            "usage": {"promptTokens": 0, "completionTokens": 0},
        }
    client = get_client()
    messages = _build_messages(user_messages)

    tools_called, tool_results, exhausted, usage = _route_tools(
        client, messages, tool_executor=tool_executor
    )
    if exhausted:
        messages.append(
            {
                "role": "user",
                "content": "工具轮次已达上限。请仅基于已有工具结果给出最终回答，不再调用工具。",
            }
        )
    deterministic_answer = deterministic_tool_answer(
        tool_results, user_text=latest_user
    )
    if deterministic_answer is not None:
        return {
            "answer": (
                enforce_compliance(deterministic_answer)
                if enforce
                else deterministic_answer.strip()
            ),
            "toolsCalled": tools_called,
            "toolResults": tool_results,
            "usage": usage,
        }
    evidence = deterministic_evidence_summary(tool_results)
    if evidence:
        messages.append(
            {
                "role": "system",
                "content": f"{_FINAL_ANSWER_POLICY}\n字段化工具证据：{evidence}",
            }
        )
    completion = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=False,
    )
    answer = completion.choices[0].message.content or MAX_ROUNDS_NOTE
    final_usage = _usage(completion)
    usage = {key: usage[key] + final_usage[key] for key in usage}

    return {
        "answer": enforce_compliance(answer) if enforce else answer.strip(),
        "toolsCalled": tools_called,
        "toolResults": tool_results,
        "usage": usage,
    }


def run_chat_stream(
    user_messages: list[dict], *, trace: ChatRunTrace | None = None
) -> Iterator[str]:
    latest_user = next(
        (
            str(message.get("content", ""))
            for message in reversed(user_messages)
            if message.get("role") == "user"
        ),
        "",
    )
    from app.ai.router import (
        deterministic_direct_response,
        deterministic_evidence_summary,
        deterministic_tool_answer,
    )

    direct = deterministic_direct_response(latest_user)
    if direct is not None:
        yield from _yield_safe_chunks(direct)
        return
    client = get_client()
    messages = _build_messages(user_messages)
    _, tool_results, exhausted, _usage_result = _route_tools(client, messages)
    if trace is not None:
        trace.tool_trace = tool_results
        trace.exhausted = exhausted
    if exhausted:
        messages.append(
            {
                "role": "user",
                "content": "工具轮次已达上限。请仅基于已有工具结果给出最终回答，不再调用工具。",
            }
        )
    deterministic_answer = deterministic_tool_answer(
        tool_results, user_text=latest_user
    )
    if deterministic_answer is not None:
        yield from _yield_safe_chunks(deterministic_answer)
        return
    evidence = deterministic_evidence_summary(tool_results)
    if evidence:
        messages.append(
            {
                "role": "system",
                "content": f"{_FINAL_ANSWER_POLICY}\n字段化工具证据：{evidence}",
            }
        )
    final_stream = client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        stream=True,
    )
    yield from _guarded_model_stream(final_stream)
