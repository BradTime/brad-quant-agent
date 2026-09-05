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
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from app.ai.deepseek import get_client
from app.ai.orchestrator import run_chat_collect, run_completion_stream
from app.ai.prompts import RESEARCH_PLANNER_PROMPT, RESEARCH_SYNTHESIS_PROMPT
from app.core.config import settings
from app.core.json_payload import JsonCorruptError, dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.research import ResearchReport

logger = logging.getLogger(__name__)


def _max_subquestions() -> int:
    return max(1, min(int(settings.research_max_subquestions or 4), 8))


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
    return subs[: _max_subquestions()] or [question]


def _assemble(question: str, findings: list[tuple[str, str, list[str]]]) -> str:
    parts = [f"【原始研究问题】\n{question}\n", "【调研发现】"]
    for i, (subq, ans, tools) in enumerate(findings, 1):
        tag = f"（用到工具：{', '.join(tools)}）" if tools else "（未调用工具）"
        parts.append(f"\n## 子问题{i}：{subq} {tag}\n{ans or '（无有效发现）'}")
    parts.append("\n请据以上调研发现综合成最终深度研究报告。")
    return "\n".join(parts)


def _persist(
    report_id: str,
    user_id: str | None,
    question: str,
    plan: list[str],
    steps: list[dict],
    content: str,
    status: str,
    error: str | None = None,
) -> None:
    with SessionLocal() as session:
        row = session.get(ResearchReport, report_id)
        if row is None:
            row = ResearchReport(id=report_id)
            session.add(row)
        row.user_id = user_id
        row.question = question[:2000]
        row.status = status
        row.content = content
        row.plan_json = dump_envelope(plan)
        row.steps_json = dump_envelope(steps)
        row.model = settings.deepseek_model
        row.error = error
        session.commit()


def stream_deep_research(
    question: str, context_hint: str = "", user_id: str | None = None
) -> Iterator[dict]:
    """流式产出研究编排事件并落库：reportId / step / plan / delta / error。

    落库状态：正常结束=ready；客户端中断（GeneratorExit）=partial（有正文）/failed；异常=failed。
    """
    question = (question or "").strip()
    if not question:
        yield {"delta": "请提供研究问题。"}
        return

    report_id = uuid.uuid4().hex
    yield {"reportId": report_id}

    try:
        _persist(report_id, user_id, question, [], [], "", "generating")
    except Exception as exc:  # noqa: BLE001
        logger.warning("研究报告 generating 落库失败: %s", exc)
        yield {"error": f"persist_failed:{exc}", "reportId": report_id, "status": "failed"}
        return

    plan: list[str] = []
    steps: list[dict] = []  # [{label, tools}] —— 落库供回看的分步轨迹
    acc: list[str] = []
    persisted_ok = False

    def _save(status: str, error: str | None = None) -> bool:
        nonlocal persisted_ok
        if persisted_ok:
            return True
        try:
            _persist(
                report_id, user_id, question, plan, steps, "".join(acc), status, error
            )
            persisted_ok = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("研究报告落库失败 status=%s: %s", status, exc)
            return False

    try:
        yield {"step": "规划研究路径", "node": "planner"}
        plan = _plan(question, context_hint)
        yield {"plan": plan}

        findings: list[tuple[str, str, list[str]]] = []
        total = len(plan)
        deadline_sec = float(settings.research_deadline_seconds or 0)
        deadline = (
            time.monotonic() + deadline_sec if deadline_sec > 0 else None
        )
        concurrency = max(1, min(int(settings.research_subquestion_concurrency or 1), total))

        def _one(subq: str) -> tuple[str, str, list[str]]:
            try:
                res = run_chat_collect(
                    [{"role": "user", "content": subq}], enforce=False
                )
                return subq, res.get("answer", ""), list(res.get("toolsCalled") or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning("子问题调研失败：%s", exc)
                return subq, f"（该子问题调研失败：{exc}）", []

        # 有界并发跑子问题；按原 plan 顺序产出进度与 findings（H25）
        ordered: list[tuple[str, str, list[str]] | None] = [None] * total
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            future_map = {
                pool.submit(_one, subq): idx for idx, subq in enumerate(plan)
            }
            completed = 0
            for fut in as_completed(future_map):
                if deadline is not None and time.monotonic() > deadline:
                    for pending in future_map:
                        pending.cancel()
                    yield {
                        "step": "研究截止时间已到，使用已完成子问题综合",
                        "node": "research",
                    }
                    break
                idx = future_map[fut]
                try:
                    ordered[idx] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    subq = plan[idx]
                    ordered[idx] = (subq, f"（该子问题调研失败：{exc}）", [])
                completed += 1
                row = ordered[idx]
                assert row is not None
                subq, _answer, tools = row
                label = f"完成 {completed}/{total}：{subq}"
                steps.append({"label": label, "tools": tools})
                yield {"step": label, "node": "research", "tools": tools or None}

        for i, subq in enumerate(plan):
            row = ordered[i]
            if row is None:
                findings.append((subq, "（未在截止时间内完成）", []))
            else:
                findings.append(row)

        yield {"step": "综合成稿", "node": "synth"}
        assembled = _assemble(question, findings)
        for piece in run_completion_stream(RESEARCH_SYNTHESIS_PROMPT, assembled):
            acc.append(piece)
            yield {"delta": piece}
        if not _save("ready"):
            yield {"error": "persist_failed", "reportId": report_id, "status": "generating"}
        else:
            yield {"reportId": report_id, "status": "ready"}
    except GeneratorExit:
        _save("partial" if acc else "failed")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("研究成稿失败：%s", exc)
        ok = _save("failed", str(exc))
        yield {"delta": f"\n\n⚠️ 研究成稿出错：{exc}"}
        yield {
            "reportId": report_id,
            "status": "failed" if ok else "generating",
            "error": str(exc),
        }

# ---------- 读取（回看） ----------


def _to_dict(row: ResearchReport, with_content: bool = True) -> dict:
    out = {
        "id": row.id,
        "userId": row.user_id,
        "question": row.question,
        "status": row.status,
        "model": row.model,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }
    if with_content:
        out["content"] = row.content
        corrupt: list[str] = []
        try:
            plan = (
                load_envelope(row.plan_json, expect="list", field="plan_json")
                if row.plan_json is not None
                else []
            )
            out["plan"] = plan
        except JsonCorruptError as exc:
            corrupt.append("plan_json")
            out["plan"] = None
            out["error"] = f"plan_json corrupt: {exc}"
        try:
            steps = (
                load_envelope(row.steps_json, expect="list", field="steps_json")
                if row.steps_json is not None
                else []
            )
            out["steps"] = steps
        except JsonCorruptError as exc:
            corrupt.append("steps_json")
            out["steps"] = None
            out["error"] = f"steps_json corrupt: {exc}"
        if corrupt:
            out["status"] = "data_corrupt"
            out["error"] = f"corrupt JSON fields: {', '.join(corrupt)}"
    return out


def list_reports(user_id: str | None, limit: int = 20) -> list[dict]:
    with SessionLocal() as session:
        stmt = (
            select(ResearchReport)
            .where(ResearchReport.user_id == user_id)
            .order_by(ResearchReport.created_at.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())
        return [_to_dict(r, with_content=False) for r in rows]


def get_report(report_id: str, user_id: str | None) -> dict | None:
    with SessionLocal() as session:
        row = session.get(ResearchReport, report_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_dict(row)
