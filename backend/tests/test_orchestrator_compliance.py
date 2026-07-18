"""Compliance must run before any model text reaches SSE callers."""

from __future__ import annotations

from types import SimpleNamespace

from app.ai import orchestrator
from app.ai.compliance import find_advice_flags


def _chunk(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=[]),
            )
        ]
    )


class _FakeClient:
    def __init__(self, pieces: list[str]):
        def create(**kwargs):
            if kwargs.get("tools"):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=None,
                                tool_calls=[
                                    _tool_call(orchestrator._FINAL_ANSWER_TOOL)
                                ],
                            )
                        )
                    ]
                )
            if kwargs.get("stream"):
                return iter(_chunk(piece) for piece in pieces)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="".join(pieces),
                            tool_calls=[],
                        )
                    )
                ]
            )

        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=create)
        )


def _tool_call(name: str = "get_market_overview"):
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name=name, arguments="{}"),
    )


def test_completion_stream_never_yields_advice_redflags(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_client", lambda: _FakeClient(["建议", "买入并全仓"]))

    pieces = list(orchestrator.run_completion_stream("system", "user"))

    assert all(find_advice_flags(piece) == [] for piece in pieces)
    assert "不构成投资建议" in "".join(pieces)


def test_chat_stream_never_yields_advice_redflags(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_client", lambda: _FakeClient(["应该买入", "，稳赚"]))

    pieces = list(orchestrator.run_chat_stream([{"role": "user", "content": "分析"}]))

    assert all(find_advice_flags(piece) == [] for piece in pieces)
    assert "无法提供确定性买卖建议" in "".join(pieces)


def test_safe_stream_content_is_preserved_with_disclaimer(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_client", lambda: _FakeClient(["客观", "数据说明"]))

    text = "".join(orchestrator.run_chat_stream([{"role": "user", "content": "分析"}]))

    assert text.startswith("客观数据说明")
    assert text.endswith("不构成投资建议。")


def test_empty_model_stream_returns_explicit_failure_text(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_client", lambda: _FakeClient([]))

    text = "".join(orchestrator.run_completion_stream("system", "user"))

    assert "暂时无法生成回答" in text


def test_closing_consumer_closes_upstream_stream(monkeypatch):
    class ClosableStream:
        closed = False

        def __iter__(self):
            yield _chunk("这是足够长的客观安全内容，用于在流结束前产生首个输出分片。")
            yield _chunk("不会被消费")

        def close(self):
            self.closed = True

    stream = ClosableStream()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: stream)
        )
    )
    monkeypatch.setattr(orchestrator, "get_client", lambda: client)

    output = orchestrator.run_completion_stream("system", "user")
    next(output)
    output.close()

    assert stream.closed is True


def test_chat_uses_separate_no_tool_stream_for_final_answer(monkeypatch):
    calls = 0

    def create(**kwargs):
        nonlocal calls
        calls += 1
        if kwargs.get("tools"):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[_tool_call(orchestrator._FINAL_ANSWER_TOOL)],
                        )
                    )
                ]
            )
        return iter([_chunk("客观最终答案")])

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(orchestrator, "get_client", lambda: client)

    text = "".join(
        orchestrator.run_chat_stream([{"role": "user", "content": "分析"}])
    )

    assert calls == 2
    assert "客观最终答案" in text


def test_collect_ignores_intermediate_text_from_tool_rounds(monkeypatch):
    messages = iter(
        [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="中间工具说明",
                            tool_calls=[_tool_call()],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[_tool_call(orchestrator._FINAL_ANSWER_TOOL)],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="最终客观结论", tool_calls=[])
                    )
                ]
            ),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: next(messages))
        )
    )
    monkeypatch.setattr(orchestrator, "get_client", lambda: client)
    monkeypatch.setattr(orchestrator, "execute_tool", lambda name, args: {"ok": True})

    result = orchestrator.run_chat_collect([{"role": "user", "content": "分析"}])

    assert "中间工具说明" not in result["answer"]
    assert "最终客观结论" in result["answer"]


def test_collect_adds_no_tool_finalizer_after_max_tool_rounds(monkeypatch):
    calls = 0

    def create(**kwargs):
        nonlocal calls
        calls += 1
        if "tools" in kwargs:
            message = SimpleNamespace(content=None, tool_calls=[_tool_call()])
        else:
            message = SimpleNamespace(content="基于工具结果的最终结论", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(orchestrator, "get_client", lambda: client)
    monkeypatch.setattr(orchestrator, "execute_tool", lambda name, args: {"ok": True})

    result = orchestrator.run_chat_collect([{"role": "user", "content": "分析"}])

    assert calls == orchestrator.MAX_TOOL_ROUNDS + 1
    assert "基于工具结果的最终结论" in result["answer"]
