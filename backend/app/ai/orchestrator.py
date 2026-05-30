"""Function-calling orchestration with streaming.

Runs up to ``MAX_TOOL_ROUNDS`` rounds: stream the model's output, accumulate any
tool-call deltas, execute the tools, feed results back, and continue until the
model produces a final text answer. User-facing text is yielded as it streams.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from app.ai.compliance import enforce_compliance, stream_compliance_tail
from app.ai.deepseek import get_client
from app.ai.prompts import SYSTEM_PROMPT
from app.ai.tools import TOOLS, execute_tool
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_ROUNDS_NOTE = "\n（已达到最大工具调用轮数。）"


def _build_messages(user_messages: list[dict]) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, *user_messages]


def _append_tool_results(
    messages: list[dict],
    assistant_content: str | None,
    calls,
) -> tuple[list[str], list[dict]]:
    tools_called: list[str] = []
    tool_results: list[dict] = []

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
        try:
            args = json.loads(c.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            result = execute_tool(name, args)
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


def run_chat_collect(user_messages: list[dict]) -> dict:
    """Non-streaming variant for evaluation/regression."""
    answer_parts: list[str] = []
    tools_called: list[str] = []
    tool_results: list[dict] = []

    client = get_client()
    messages = _build_messages(user_messages)

    for _ in range(MAX_TOOL_ROUNDS):
        completion = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=False,
        )
        msg = completion.choices[0].message
        if msg.content:
            answer_parts.append(msg.content)

        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            break

        called, results = _append_tool_results(messages, msg.content, calls)
        tools_called.extend(called)
        tool_results.extend(results)

    return {
        "answer": enforce_compliance("".join(answer_parts)),
        "toolsCalled": tools_called,
        "toolResults": tool_results,
    }


def run_chat_stream(user_messages: list[dict]) -> Iterator[str]:
    client = get_client()
    messages = _build_messages(user_messages)
    streamed: list[str] = []

    def emit(piece: str) -> str:
        streamed.append(piece)
        return piece

    def finish() -> Iterator[str]:
        tail = stream_compliance_tail("".join(streamed))
        if tail:
            streamed.append(tail)
            yield tail

    for _ in range(MAX_TOOL_ROUNDS):
        stream = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True,
        )

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                content_parts.append(delta.content)
                yield emit(delta.content)
            for tcd in getattr(delta, "tool_calls", None) or []:
                slot = tool_calls.setdefault(tcd.index, {"id": None, "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                fn = getattr(tcd, "function", None)
                if fn is not None:
                    if fn.name:
                        slot["name"] += fn.name
                    if fn.arguments:
                        slot["args"] += fn.arguments

        if not tool_calls:
            yield from finish()
            return

        messages.append(
            {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": slot["id"],
                        "type": "function",
                        "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
                    }
                    for slot in tool_calls.values()
                ],
            }
        )
        for slot in tool_calls.values():
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = execute_tool(slot["name"], args)
            except Exception as exc:  # noqa: BLE001
                logger.warning("工具 %s 执行失败: %s", slot["name"], exc)
                result = {"error": f"工具执行失败: {exc}"}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": slot["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    yield emit(MAX_ROUNDS_NOTE)
    yield from finish()
