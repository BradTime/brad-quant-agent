"""Transactional orchestration for the auditable M4 decision chain."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.decision import protocol
from app.models.decision import DecisionEvent, DecisionRun
from app.models.prediction import PortfolioAllocationDecision
from app.services import authoritative_allocation

RUN_LEASE = timedelta(minutes=5)


class DecisionConflictError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _request_hash(codes: list[str]) -> str:
    return _hash(
        {
            "protocolVersion": protocol.PROTOCOL_VERSION,
            "codes": sorted(codes),
        }
    )


def _reserve(
    user_id: str,
    *,
    codes: list[str],
    as_of: date,
) -> tuple[str, bool, str | None]:
    request_sha256 = _request_hash(codes)
    run_id = str(uuid4())
    claim_token = str(uuid4())
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        insert = (
            sqlite_insert
            if session.get_bind().dialect.name == "sqlite"
            else pg_insert
        )
        result = session.execute(
            insert(DecisionRun)
            .values(
                id=run_id,
                user_id=user_id,
                user_id_snapshot=user_id,
                as_of=as_of,
                request_sha256=request_sha256,
                protocol_version=protocol.PROTOCOL_VERSION,
                status="running",
                current_stage="reserved",
                claim_token=claim_token,
                severe_disagreement=False,
                event_count=0,
                updated_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "user_id_snapshot",
                    "as_of",
                    "request_sha256",
                ]
            )
        )
        if result.rowcount:
            return run_id, True, claim_token
        existing = session.execute(
            select(DecisionRun)
            .where(
                DecisionRun.user_id_snapshot == user_id,
                DecisionRun.as_of == as_of,
                DecisionRun.request_sha256 == request_sha256,
            )
            .with_for_update()
        ).scalar_one()
        updated_at = existing.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        stale = (
            existing.status == "running"
            and now - updated_at >= RUN_LEASE
        )
        if existing.status == "failed" or stale:
            existing.status = "running"
            existing.current_stage = "reserved"
            existing.error_code = None
            existing.claim_token = claim_token
            existing.updated_at = now
            return existing.id, True, claim_token
        return existing.id, False, None


def _append_event(
    session,
    *,
    run_id: str,
    sequence: int,
    stage: str,
    actor: str,
    inputs: Any,
    output: dict[str, Any],
    previous: str | None,
) -> str:
    input_sha256 = _hash(inputs)
    output_sha256 = _hash(output)
    event_sha256 = _hash(
        {
            "runId": run_id,
            "sequence": sequence,
            "stage": stage,
            "actor": actor,
            "inputSha256": input_sha256,
            "outputSha256": output_sha256,
            "previousEventSha256": previous,
            "protocolVersion": protocol.PROTOCOL_VERSION,
        }
    )
    session.add(
        DecisionEvent(
            id=str(uuid4()),
            run_id=run_id,
            sequence=sequence,
            stage=stage,
            actor=actor,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            previous_event_sha256=previous,
            event_sha256=event_sha256,
            payload_json=dump_envelope(
                {"input": inputs, "output": output}
            ),
        )
    )
    return event_sha256


def _mark_failed(
    run_id: str, claim_token: str, exc: Exception
) -> None:
    with SessionLocal.begin() as session:
        row = session.execute(
            select(DecisionRun)
            .where(
                DecisionRun.id == run_id,
                DecisionRun.claim_token == claim_token,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is not None and row.status == "running":
            row.status = "failed"
            row.current_stage = "failed"
            row.error_code = type(exc).__name__[:64]
            row.claim_token = None


def _verified_allocation(
    session,
    *,
    allocation_id: str,
    user_id: str,
    as_of: date,
    requested_codes: list[str],
) -> tuple[PortfolioAllocationDecision, dict[str, Any]]:
    row = session.get(PortfolioAllocationDecision, allocation_id)
    if (
        row is None
        or row.user_id_snapshot != user_id
        or row.as_of != as_of
    ):
        raise ValueError("权威组合证据不存在、日期不符或不属于当前用户")
    payload = load_envelope(
        row.payload_json,
        expect="dict",
        field="portfolio_allocation_decision.payload_json",
    )
    if set(payload) != {"input", "output"}:
        raise ValueError("权威组合证据结构无效")
    if (
        _hash(payload["input"]) != row.input_sha256
        or _hash(payload["output"]) != row.output_sha256
    ):
        raise ValueError("权威组合证据 Hash 校验失败")
    predictions = payload["input"].get("predictions")
    if (
        not isinstance(predictions, list)
        or not predictions
        or any(
            not isinstance(prediction, dict)
            or prediction.get("signalDate") != as_of.isoformat()
            for prediction in predictions
        )
    ):
        raise ValueError("权威组合预测日期与决策日不一致")
    prediction_codes = {
        str(prediction["code"]) for prediction in predictions
    }
    if not set(requested_codes).issubset(prediction_codes):
        raise ValueError("权威组合证据未覆盖请求标的")
    return row, payload


def run(
    user_id: str,
    *,
    codes: list[str],
    as_of: date,
) -> dict[str, Any]:
    run_id, should_run, claim_token = _reserve(
        user_id, codes=codes, as_of=as_of
    )
    if not should_run:
        existing = get(user_id, run_id)
        if existing["status"] == "running":
            raise DecisionConflictError("相同决策请求正在运行")
        return existing
    assert claim_token is not None
    try:
        with SessionLocal() as session:
            reserved = session.execute(
                select(DecisionRun).where(
                    DecisionRun.id == run_id,
                    DecisionRun.claim_token == claim_token,
                )
            ).scalar_one()
            allocation_id = reserved.allocation_decision_id
        if allocation_id is None:
            allocation_result = authoritative_allocation.preview(
                user_id,
                requested_codes=codes,
                as_of=as_of,
            )
            allocation_id = allocation_result["decisionId"]
            with SessionLocal.begin() as session:
                run_row = session.execute(
                    select(DecisionRun)
                    .where(
                        DecisionRun.id == run_id,
                        DecisionRun.claim_token == claim_token,
                    )
                    .with_for_update()
                ).scalar_one()
                _verified_allocation(
                    session,
                    allocation_id=allocation_id,
                    user_id=user_id,
                    as_of=as_of,
                    requested_codes=codes,
                )
                run_row.allocation_decision_id = allocation_id
                run_row.current_stage = "evidence_bound"
                run_row.updated_at = datetime.now(UTC)
        with SessionLocal.begin() as session:
            run_row = session.execute(
                select(DecisionRun)
                .where(
                    DecisionRun.id == run_id,
                    DecisionRun.claim_token == claim_token,
                )
                .with_for_update()
            ).scalar_one()
            if run_row.status != "running":
                raise ValueError("决策运行状态已变化")
            allocation_row, allocation_payload = _verified_allocation(
                session,
                allocation_id=run_row.allocation_decision_id,
                user_id=user_id,
                as_of=as_of,
                requested_codes=codes,
            )
            inputs = allocation_payload["input"]
            allocation = allocation_payload["output"]
            research = protocol.researcher(inputs, allocation)
            contrarian = protocol.contrarian_blind(inputs)
            examination_one = protocol.cross_examine(
                research, contrarian, round_number=1
            )
            examination_two = protocol.cross_examine(
                research, contrarian, round_number=2
            )
            committee = protocol.investment_committee(
                research,
                contrarian,
                [examination_one, examination_two],
            )
            risk = protocol.risk_officer(committee, allocation)
            stages = [
                (
                    "researcher",
                    "researcher",
                    {
                        "allocationDecisionId": allocation_row.id,
                        "allocationInputSha256": (
                            allocation_row.input_sha256
                        ),
                        "allocationOutputSha256": (
                            allocation_row.output_sha256
                        ),
                        "allocationEvidence": allocation_payload,
                    },
                    research,
                ),
                (
                    "contrarian_blind",
                    "contrarian",
                    {
                        "allocationInputSha256": (
                            allocation_row.input_sha256
                        ),
                        "researcherClaimAvailable": False,
                    },
                    contrarian,
                ),
                (
                    "cross_examination_1",
                    "researcher_and_contrarian",
                    {"research": research, "contrarian": contrarian},
                    examination_one,
                ),
                (
                    "cross_examination_2",
                    "researcher_and_contrarian",
                    {
                        "research": research,
                        "contrarian": contrarian,
                        "roundOne": examination_one,
                    },
                    examination_two,
                ),
                (
                    "investment_committee",
                    "investment_committee",
                    {
                        "research": research,
                        "contrarian": contrarian,
                        "examinations": [
                            examination_one,
                            examination_two,
                        ],
                    },
                    committee,
                ),
                (
                    "risk_officer",
                    "risk_officer",
                    {
                        "committee": committee,
                        "allocationOutputSha256": (
                            allocation_row.output_sha256
                        ),
                    },
                    risk,
                ),
            ]
            previous = None
            for sequence, (
                stage,
                actor,
                stage_inputs,
                output,
            ) in enumerate(stages, start=1):
                previous = _append_event(
                    session,
                    run_id=run_id,
                    sequence=sequence,
                    stage=stage,
                    actor=actor,
                    inputs=stage_inputs,
                    output=output,
                    previous=previous,
                )
                run_row.current_stage = stage
            run_row.allocation_decision_id = allocation_row.id
            run_row.severe_disagreement = bool(
                committee["severeDisagreement"]
            )
            run_row.status = (
                "vetoed" if risk["veto"] else "approved_candidate"
            )
            run_row.event_count = len(stages)
            run_row.terminal_event_sha256 = previous
            run_row.claim_token = None
            run_row.completed_at = datetime.now(UTC)
        return get(user_id, run_id)
    except Exception as exc:
        _mark_failed(run_id, claim_token, exc)
        raise


def _serialize(run_row: DecisionRun, events: list[DecisionEvent]) -> dict[str, Any]:
    if len(events) != run_row.event_count:
        raise RuntimeError("决策审计事件数量与运行锚点不匹配")
    previous = None
    serialized_events = []
    for event in events:
        payload = load_envelope(
            event.payload_json,
            expect="dict",
            field="decision_event.payload_json",
        )
        stage_inputs = payload["input"]
        output = payload["output"]
        if event.previous_event_sha256 != previous:
            raise RuntimeError("决策审计链前序 Hash 不匹配")
        expected = _hash(
            {
                "runId": run_row.id,
                "sequence": event.sequence,
                "stage": event.stage,
                "actor": event.actor,
                "inputSha256": event.input_sha256,
                "outputSha256": event.output_sha256,
                "previousEventSha256": previous,
                "protocolVersion": run_row.protocol_version,
            }
        )
        if (
            _hash(stage_inputs) != event.input_sha256
            or _hash(output) != event.output_sha256
            or expected != event.event_sha256
        ):
            raise RuntimeError("决策审计事件 Hash 校验失败")
        previous = event.event_sha256
        serialized_events.append(
            {
                "sequence": event.sequence,
                "stage": event.stage,
                "actor": event.actor,
                "inputSha256": event.input_sha256,
                "outputSha256": event.output_sha256,
                "previousEventSha256": event.previous_event_sha256,
                "eventSha256": event.event_sha256,
                "output": output,
                "createdAt": event.created_at.isoformat(),
            }
        )
    if previous != run_row.terminal_event_sha256:
        raise RuntimeError("决策审计链尾 Hash 与运行锚点不匹配")
    if run_row.completed_at is not None and run_row.event_count != 6:
        raise RuntimeError("已完成决策缺少完整六阶段审计")
    return {
        "id": run_row.id,
        "asOf": run_row.as_of.isoformat(),
        "status": run_row.status,
        "protocolVersion": run_row.protocol_version,
        "currentStage": run_row.current_stage,
        "severeDisagreement": run_row.severe_disagreement,
        "errorCode": run_row.error_code,
        "allocationDecisionId": run_row.allocation_decision_id,
        "createdAt": run_row.created_at.isoformat(),
        "completedAt": (
            run_row.completed_at.isoformat()
            if run_row.completed_at
            else None
        ),
        "events": serialized_events,
    }


def get(user_id: str, run_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        run_row = session.execute(
            select(DecisionRun).where(
                DecisionRun.id == run_id,
                DecisionRun.user_id == user_id,
            )
        ).scalar_one_or_none()
        if run_row is None:
            raise ValueError("决策记录不存在")
        events = session.execute(
            select(DecisionEvent)
            .where(DecisionEvent.run_id == run_id)
            .order_by(DecisionEvent.sequence)
        ).scalars().all()
        return _serialize(run_row, events)


def list_runs(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(DecisionRun)
            .where(DecisionRun.user_id == user_id)
            .order_by(DecisionRun.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "id": row.id,
                "asOf": row.as_of.isoformat(),
                "status": row.status,
                "currentStage": row.current_stage,
                "severeDisagreement": row.severe_disagreement,
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows
        ]
