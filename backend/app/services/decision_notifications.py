"""Persist and dispatch privacy-minimized decision-room notifications."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.room import DecisionNotification
from app.ws.notify import notify_user_threadsafe

ALLOWED_EVENTS = {
    "decision.severe_disagreement": "critical",
    "decision.risk_veto": "warning",
    "decision.kill_switch": "critical",
}


def _hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def emit(
    user_id: str,
    *,
    event_type: str,
    resource_id: str,
    message: str,
) -> dict:
    if event_type not in ALLOWED_EVENTS:
        raise ValueError("通知事件类型无效")
    notification_id = str(uuid4())
    payload = {
        "notificationId": notification_id,
        "eventType": event_type,
        "severity": ALLOWED_EVENTS[event_type],
        "resourceId": resource_id,
        "message": message[:160],
        "roomPath": f"/decisions?decision={resource_id}",
    }
    try:
        with SessionLocal.begin() as session:
            session.add(
                DecisionNotification(
                    id=notification_id,
                    user_id=user_id,
                    user_id_snapshot=user_id,
                    event_type=event_type,
                    severity=ALLOWED_EVENTS[event_type],
                    resource_id=resource_id,
                    payload_json=dump_envelope(payload),
                    payload_sha256=_hash(payload),
                    ws_status="pending",
                    feishu_status=(
                        "pending"
                        if settings.feishu_webhook_url
                        else "disabled"
                    ),
                )
            )
    except IntegrityError:
        with SessionLocal() as session:
            existing = session.execute(
                select(DecisionNotification).where(
                    DecisionNotification.user_id_snapshot == user_id,
                    DecisionNotification.event_type == event_type,
                    DecisionNotification.resource_id == resource_id,
                )
            ).scalar_one()
            notification_id = existing.id
        delivered = _deliver(notification_id)
        return {**delivered, "deduplicated": True}
    delivered = _deliver(notification_id)
    return {**delivered, "deduplicated": False}


def _deliver(notification_id: str) -> dict:
    now = datetime.now(UTC)
    token = str(uuid4())
    with SessionLocal.begin() as session:
        row = session.execute(
            select(DecisionNotification)
            .where(DecisionNotification.id == notification_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            raise ValueError("决策通知不存在")
        started = row.delivery_started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if (
            row.delivery_token
            and started is not None
            and started > now - timedelta(minutes=5)
        ):
            return {
                "id": row.id,
                "wsStatus": row.ws_status,
                "feishuStatus": row.feishu_status,
            }
        next_attempt = row.feishu_next_attempt_at
        if next_attempt is not None and next_attempt.tzinfo is None:
            next_attempt = next_attempt.replace(tzinfo=UTC)
        send_ws = row.ws_status == "pending"
        send_feishu = row.feishu_status == "pending" and (
            next_attempt is None or next_attempt <= now
        )
        if not send_ws and not send_feishu:
            return {
                "id": row.id,
                "wsStatus": row.ws_status,
                "feishuStatus": row.feishu_status,
            }
        payload = load_envelope(
            row.payload_json,
            expect="dict",
            field="decision_notification.payload_json",
        )
        if _hash(payload) != row.payload_sha256:
            raise RuntimeError("决策通知 Hash 校验失败")
        user_id = row.user_id_snapshot
        event_type = row.event_type
        row.delivery_token = token
        row.delivery_started_at = now
    ws_status = None
    if send_ws:
        ws_status = (
            "published"
            if notify_user_threadsafe(user_id, event_type, payload)
            else "pending"
        )
    feishu_status = None
    if send_feishu:
        try:
            response = httpx.post(
                settings.feishu_webhook_url,
                json={
                    "msg_type": "text",
                    "content": {
                        "text": (
                            f"[{payload['notificationId']}] "
                            f"[{payload['severity']}] {payload['message']}\n"
                            f"请登录站内查看：{payload['roomPath']}"
                        )
                    },
                },
                timeout=settings.feishu_timeout_seconds,
                follow_redirects=False,
            )
            response.raise_for_status()
            body = response.json()
            feishu_status = (
                "sent"
                if body.get("code", body.get("StatusCode")) == 0
                else "failed"
            )
        except (httpx.HTTPError, ValueError, TypeError):
            feishu_status = "failed"
    with SessionLocal.begin() as session:
        row = session.execute(
            select(DecisionNotification)
            .where(
                DecisionNotification.id == notification_id,
                DecisionNotification.delivery_token == token,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if row is None:
            return {
                "id": notification_id,
                "wsStatus": "unknown",
                "feishuStatus": "unknown",
            }
        if ws_status is not None:
            row.ws_status = ws_status
        if feishu_status is not None:
            row.feishu_attempts += 1
            if feishu_status == "sent":
                row.feishu_status = "sent"
                row.feishu_next_attempt_at = None
            else:
                row.feishu_status = "pending"
                delay = min(3600, 60 * (2 ** (row.feishu_attempts - 1)))
                row.feishu_next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=delay
                )
        row.delivery_token = None
        row.delivery_started_at = None
        result = {
            "id": notification_id,
            "wsStatus": row.ws_status,
            "feishuStatus": row.feishu_status,
        }
    return result


def retry_pending(*, limit: int = 100) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    with SessionLocal() as session:
        ids = session.execute(
            select(DecisionNotification.id)
            .where(
                (DecisionNotification.ws_status == "pending")
                | (
                    (DecisionNotification.feishu_status == "pending")
                    & (
                        DecisionNotification.feishu_next_attempt_at.is_(
                            None
                        )
                        | (
                            DecisionNotification.feishu_next_attempt_at
                            <= datetime.now(UTC)
                        )
                    )
                ),
                (
                    DecisionNotification.delivery_token.is_(None)
                    | (DecisionNotification.delivery_started_at <= cutoff)
                ),
            )
            .order_by(DecisionNotification.created_at)
            .limit(limit)
        ).scalars().all()
    for notification_id in ids:
        try:
            _deliver(notification_id)
        except Exception:
            continue
    return len(ids)


def list_for_user(user_id: str, *, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
            select(DecisionNotification)
            .where(DecisionNotification.user_id == user_id)
            .order_by(DecisionNotification.created_at.desc())
            .limit(limit)
        ).scalars().all()
        result = []
        for row in rows:
            payload = load_envelope(
                row.payload_json,
                expect="dict",
                field="decision_notification.payload_json",
            )
            if _hash(payload) != row.payload_sha256:
                raise RuntimeError("决策通知 Hash 校验失败")
            result.append(
                {
                    "id": row.id,
                    **payload,
                    "wsStatus": row.ws_status,
                    "feishuStatus": row.feishu_status,
                    "createdAt": row.created_at.isoformat(),
                }
            )
        return result
