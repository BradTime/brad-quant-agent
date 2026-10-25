"""Private decision-room controls and human override audit."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.decision import DecisionEvent, DecisionRun
from app.models.prediction import (
    PortfolioAllocationDecision,
    PortfolioRiskProfile,
)
from app.models.room import (
    DecisionOverride,
    DecisionRoomAudit,
    DecisionRoomControl,
)
from app.models.user import User
from app.services import authoritative_allocation, step_up, trading

MODES = {"research_only", "manual_review", "simulation_ready"}
logger = logging.getLogger(__name__)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _insert(session):
    return (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert
    )


def _control(session, user_id: str) -> DecisionRoomControl:
    session.execute(
        _insert(session)(DecisionRoomControl)
        .values(user_id=user_id, mode="research_only")
        .on_conflict_do_nothing(
            index_elements=[DecisionRoomControl.user_id]
        )
    )
    return session.execute(
        select(DecisionRoomControl)
        .where(DecisionRoomControl.user_id == user_id)
        .with_for_update()
    ).scalar_one()


def _audit(
    session,
    *,
    user_id: str,
    action: str,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> str:
    evidence = {
        "userIdSnapshot": user_id,
        "action": action,
        "reason": reason,
        "before": before,
        "after": after,
    }
    audit_id = str(uuid4())
    session.add(
        DecisionRoomAudit(
            id=audit_id,
            user_id=user_id,
            user_id_snapshot=user_id,
            action=action,
            reason=reason,
            before_json=dump_envelope(before),
            after_json=dump_envelope(after),
            evidence_sha256=_hash(evidence),
        )
    )
    return audit_id


def state(user_id: str) -> dict[str, Any]:
    account = trading.get_account(user_id)
    with SessionLocal.begin() as session:
        control = _control(session, user_id)
        profile = authoritative_allocation._risk_profile(
            session, user_id, float(account["totalAssets"])
        )
        return {
            "mode": control.mode,
            "killSwitchActive": profile.kill_switch_active,
            "capitalLimit": profile.capital_limit,
            "leverageLimit": profile.leverage_limit,
            "highWaterMark": profile.high_water_mark,
            "executionEnabled": False,
        }


def change_mode(
    user: User,
    *,
    mode: str,
    reason: str,
    step_up_token: str,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError("决策室模式无效")
    reason = reason.strip()
    if len(reason) < 10:
        raise ValueError("模式切换原因至少 10 个字符")
    with SessionLocal.begin() as session:
        locked_user = session.execute(
            select(User)
            .where(User.id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        if locked_user is None:
            raise ValueError("用户不存在")
        step_up.consume(
            session,
            user=locked_user,
            token=step_up_token,
            purpose="change_decision_mode",
        )
        control = _control(session, str(user.id))
        before = {"mode": control.mode}
        control.mode = mode
        after = {"mode": mode, "executionEnabled": False}
        audit_id = _audit(
            session,
            user_id=str(user.id),
            action="change_mode",
            reason=reason,
            before=before,
            after=after,
        )
        return {**after, "auditId": audit_id}


def activate_kill_switch(user_id: str, *, reason: str) -> dict[str, Any]:
    reason = reason.strip()
    if len(reason) < 10:
        raise ValueError("触发 Kill Switch 的原因至少 10 个字符")
    account = trading.get_account(user_id)
    with SessionLocal.begin() as session:
        user = session.execute(
            select(User).where(User.id == user_id).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("用户不存在")
        profile = authoritative_allocation._risk_profile(
            session, user_id, float(account["totalAssets"])
        )
        before = {"killSwitchActive": profile.kill_switch_active}
        profile.kill_switch_active = True
        after = {"killSwitchActive": True}
        audit_id = _audit(
            session,
            user_id=user_id,
            action="activate_kill_switch",
            reason=reason,
            before=before,
            after=after,
        )
        result = {**after, "auditId": audit_id}
    try:
        from app.services import broker_gateway

        broker_gateway.revoke_for_kill_switch(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kill Switch 券商队列撤销失败: %s", type(exc).__name__)
    try:
        from app.services import decision_notifications

        decision_notifications.emit(
            user_id,
            event_type="decision.kill_switch",
            resource_id=audit_id,
            message="Kill Switch 已由用户人工触发。",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kill Switch 通知投递失败: %s", type(exc).__name__)
    return result


def release_kill_switch(
    user: User,
    *,
    reason: str,
    step_up_token: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if len(reason) < 10:
        raise ValueError("解除 Kill Switch 的原因至少 10 个字符")
    with SessionLocal.begin() as session:
        locked_user = session.execute(
            select(User)
            .where(User.id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        profile = session.execute(
            select(PortfolioRiskProfile)
            .where(PortfolioRiskProfile.user_id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        if locked_user is None or profile is None:
            raise ValueError("风险档案不存在")
        if not profile.kill_switch_active:
            raise ValueError("Kill Switch 当前未触发")
        step_up.consume(
            session,
            user=locked_user,
            token=step_up_token,
            purpose="release_kill_switch",
        )
        before = {"killSwitchActive": profile.kill_switch_active}
        profile.kill_switch_active = False
        after = {"killSwitchActive": False}
        audit_id = _audit(
            session,
            user_id=str(user.id),
            action="release_kill_switch",
            reason=reason,
            before=before,
            after=after,
        )
        return {**after, "auditId": audit_id}


def _validate_override_weights(
    weights: dict[str, float],
    inputs: dict[str, Any],
    approved_codes: set[str],
) -> dict[str, float]:
    predictions = {
        prediction["code"]: prediction
        for prediction in inputs["predictions"]
    }
    if set(weights) - approved_codes:
        raise ValueError("人工覆盖包含未获委员会和风险官批准的标的")
    normalized = {}
    for code, raw_weight in weights.items():
        if (
            isinstance(raw_weight, bool)
            or not isinstance(raw_weight, (int, float))
            or not math.isfinite(float(raw_weight))
            or not 0 <= float(raw_weight) <= 0.20
        ):
            raise ValueError("人工覆盖单票权重必须在 [0,20%]")
        normalized[code] = float(raw_weight)
    risk_profile = inputs["riskProfile"]
    capital = float(risk_profile["capitalLimit"])
    leverage = float(risk_profile["leverageLimit"])
    if sum(normalized.values()) > 1 + leverage / capital + 1e-9:
        raise ValueError("人工覆盖超过总敞口限制")
    industries = inputs["industries"]
    by_industry: dict[str, float] = {}
    for code, weight in normalized.items():
        industry = industries[code]
        by_industry[industry] = by_industry.get(industry, 0.0) + weight
    if any(weight > 0.30 + 1e-9 for weight in by_industry.values()):
        raise ValueError("人工覆盖超过行业 30% 限制")
    predicted_loss = sum(
        weight
        * max(
            0.0,
            -float(predictions[code]["returnInterval80"]["low"]),
        )
        for code, weight in normalized.items()
    )
    if predicted_loss > 0.02 + 1e-9:
        raise ValueError("人工覆盖超过预计日损失 2% 限制")
    return normalized


def override(
    user: User,
    *,
    run_id: str,
    action: str,
    reason: str,
    weights: dict[str, float] | None,
    step_up_token: str,
) -> dict[str, Any]:
    if action not in {"accept", "reject", "modify"}:
        raise ValueError("人工覆盖动作无效")
    reason = reason.strip()
    if len(reason) < 10:
        raise ValueError("人工覆盖原因至少 10 个字符")
    with SessionLocal.begin() as session:
        locked_user = session.execute(
            select(User)
            .where(User.id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        run_row = session.execute(
            select(DecisionRun)
            .where(
                DecisionRun.id == run_id,
                DecisionRun.user_id == str(user.id),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if locked_user is None or run_row is None:
            raise ValueError("决策记录不存在")
        if run_row.status not in {"approved_candidate", "vetoed"}:
            raise ValueError("决策尚未完成")
        if action != "reject" and run_row.status != "approved_candidate":
            raise ValueError("人工不得绕过投资委员会或风险官否决")
        step_up.consume(
            session,
            user=locked_user,
            token=step_up_token,
            purpose="override_decision",
        )
        profile = session.execute(
            select(PortfolioRiskProfile)
            .where(PortfolioRiskProfile.user_id == str(user.id))
            .with_for_update()
        ).scalar_one_or_none()
        control = _control(session, str(user.id))
        if profile is None:
            raise ValueError("风险档案不存在")
        if action != "reject" and control.mode == "research_only":
            raise ValueError("研究模式只允许拒绝候选")
        if action != "reject" and profile.kill_switch_active:
            raise ValueError("Kill Switch 已触发，只允许拒绝候选")
        allocation = session.get(
            PortfolioAllocationDecision,
            run_row.allocation_decision_id,
        )
        if allocation is None:
            raise ValueError("决策缺少 M3 权威证据")
        payload = load_envelope(
            allocation.payload_json,
            expect="dict",
            field="portfolio_allocation_decision.payload_json",
        )
        if (
            _hash(payload.get("input")) != allocation.input_sha256
            or _hash(payload.get("output")) != allocation.output_sha256
        ):
            raise ValueError("M3 权威证据 Hash 校验失败")
        risk_event = session.execute(
            select(DecisionEvent).where(
                DecisionEvent.run_id == run_id,
                DecisionEvent.sequence == run_row.event_count,
            )
        ).scalar_one_or_none()
        if (
            risk_event is None
            or risk_event.stage != "risk_officer"
            or risk_event.event_sha256
            != run_row.terminal_event_sha256
        ):
            raise ValueError("M4 风险官审计锚点无效")
        risk_payload = load_envelope(
            risk_event.payload_json,
            expect="dict",
            field="decision_event.payload_json",
        )
        risk_output = risk_payload.get("output")
        if (
            not isinstance(risk_output, dict)
            or _hash(risk_payload.get("input"))
            != risk_event.input_sha256
            or _hash(risk_output) != risk_event.output_sha256
            or risk_output.get("veto") is not False
            or risk_output.get("executionApproved") is not False
            or not isinstance(
                risk_output.get("approvedCandidateWeights"), dict
            )
        ):
            raise ValueError("M4 风险官未批准研究候选")
        approved_codes = set(
            risk_output["approvedCandidateWeights"]
        )
        normalized_weights = {}
        if action == "modify":
            if not weights:
                raise ValueError("修改动作必须提交非空目标权重")
            normalized_weights = _validate_override_weights(
                weights, payload["input"], approved_codes
            )
        elif weights:
            raise ValueError("仅修改动作允许提交目标权重")
        evidence = {
            "runId": run_id,
            "runTerminalSha256": run_row.terminal_event_sha256,
            "allocationInputSha256": allocation.input_sha256,
            "allocationOutputSha256": allocation.output_sha256,
            "action": action,
            "reason": reason,
            "weights": normalized_weights,
            "executionApproved": False,
        }
        override_id = str(uuid4())
        session.add(
            DecisionOverride(
                id=override_id,
                run_id=run_id,
                user_id=str(user.id),
                user_id_snapshot=str(user.id),
                action=action,
                reason=reason,
                weights_json=dump_envelope(normalized_weights),
                evidence_sha256=_hash(evidence),
            )
        )
        return {
            "id": override_id,
            "action": action,
            "weights": normalized_weights,
            "executionApproved": False,
            "createdAt": datetime.now(UTC).isoformat(),
        }
