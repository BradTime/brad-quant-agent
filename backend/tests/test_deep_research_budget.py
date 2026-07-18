"""H25：深研子问题有界并发与 plan 截断。"""

from __future__ import annotations

import time

from app.ai import deep_research


def test_plan_truncated_to_settings_max(monkeypatch):
    monkeypatch.setattr(deep_research.settings, "research_max_subquestions", 2)
    monkeypatch.setattr(
        deep_research,
        "get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Ch",
                    (),
                    {
                        "completions": type(
                            "Co",
                            (),
                            {
                                "create": staticmethod(
                                    lambda **_k: type(
                                        "R",
                                        (),
                                        {
                                            "choices": [
                                                type(
                                                    "Chc",
                                                    (),
                                                    {
                                                        "message": type(
                                                            "M",
                                                            (),
                                                            {
                                                                "content": '["a","b","c","d"]'
                                                            },
                                                        )()
                                                    },
                                                )()
                                            ]
                                        },
                                    )()
                                )
                            },
                        )()
                    },
                )()
            },
        )(),
    )
    plan = deep_research._plan("q")
    assert plan == ["a", "b"]


def test_stream_runs_subquestions_concurrently(monkeypatch):
    monkeypatch.setattr(deep_research.settings, "research_subquestion_concurrency", 2)
    monkeypatch.setattr(deep_research.settings, "research_deadline_seconds", 0)
    monkeypatch.setattr(deep_research, "_persist", lambda *a, **k: None)
    monkeypatch.setattr(deep_research, "_plan", lambda *_a, **_k: ["q1", "q2"])

    started: list[float] = []

    def slow_collect(messages, enforce=False):  # noqa: ANN001
        started.append(time.monotonic())
        time.sleep(0.15)
        return {"answer": "ok", "toolsCalled": []}

    monkeypatch.setattr(deep_research, "run_chat_collect", slow_collect)
    monkeypatch.setattr(
        deep_research,
        "run_completion_stream",
        lambda *_a, **_k: iter(["正文"]),
    )

    t0 = time.monotonic()
    events = list(deep_research.stream_deep_research("测试", user_id="u1"))
    elapsed = time.monotonic() - t0
    assert any(e.get("status") == "ready" for e in events if isinstance(e, dict))
    # 并行应明显快于串行 0.3s
    assert elapsed < 0.28
    assert len(started) == 2
