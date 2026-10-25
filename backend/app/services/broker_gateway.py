"""Fail-closed EMT simulation outbox, bridge lease, and reconciliation."""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.broker import base as broker_base
from app.broker import emt
from app.broker.base import BrokerAdapter, BrokerOrderRequest
from app.core.config import settings
from app.core.json_payload import dump_envelope
from app.db.session import SessionLocal
from app.models.broker import (
    BrokerBinding,
    BrokerEvent,
    BrokerFilingProfile,
    BrokerOrder,
    BrokerRateWindow,
    BrokerReconciliation,
    BrokerRehearsalRun,
)
from app.models.prediction import PortfolioRiskProfile
from app.models.user import User
from app.services import step_up

BRIDGE_LEASE = timedelta(seconds=30)
SEND_UNCERTAIN_AFTER = timedelta(seconds=30)
REHEARSAL_MAX_NOTIONAL = 20_000.0


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str):
        try:
            return _aware(
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            )
        except ValueError:
            return None
    return None


def _safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _safe(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _cipher() -> Fernet:
    return Fernet(settings.auth_outbox_encryption_key.encode())


def _encrypt(value: Any) -> str:
    return _cipher().encrypt(
        json.dumps(
            _safe(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).decode()


def _decrypt(ciphertext: str) -> Any:
    try:
        return json.loads(
            _cipher().decrypt(ciphertext.encode()).decode()
        )
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("券商敏感证据不可解密") from exc


def implementation_sha256() -> str:
    from app.broker import emt_bridge
    from app.core import config

    source = "\n".join(
        (
            inspect.getsource(broker_base),
            inspect.getsource(emt),
            inspect.getsource(emt_bridge),
            inspect.getsource(config),
            inspect.getsource(sys.modules[__name__]),
            _hash(
                {
                    "environment": settings.emt_environment,
                    "accountIdSha256": hashlib.sha256(
                        settings.emt_account_id.encode()
                    ).hexdigest(),
                    "strategyIdSha256": hashlib.sha256(
                        settings.emt_strategy_id.encode()
                    ).hexdigest(),
                    "servAddr": settings.emt_serv_addr,
                    "maxOrdersPerSecond": (
                        settings.emt_max_orders_per_second
                    ),
                    "simulationConfirmation": (
                        settings.emt_simulation_confirmation
                    ),
                }
            ),
        )
    )
    return hashlib.sha256(source.encode()).hexdigest()


def register_filing(
    *,
    user_id: str,
    reviewed_by_user_id: str,
    filing_reference: str,
    evidence_document_sha256: str,
    professional_eligibility_confirmed: bool,
    broker_simulation_permission_confirmed: bool,
) -> dict[str, Any]:
    if (
        len(evidence_document_sha256) != 64
        or any(
            char not in "0123456789abcdef"
            for char in evidence_document_sha256.lower()
        )
    ):
        raise ValueError("报备证据必须提供 SHA-256")
    if not filing_reference.strip():
        raise ValueError("报备引用不能为空")
    profile_id = str(uuid4())
    now = _now()
    with SessionLocal.begin() as session:
        previous = session.execute(
            select(BrokerFilingProfile)
            .where(
                BrokerFilingProfile.user_id == user_id,
                BrokerFilingProfile.invalidated_at.is_(None),
            )
            .with_for_update()
        ).scalars().all()
        for row in previous:
            row.invalidated_at = now
        session.add(
            BrokerFilingProfile(
                id=profile_id,
                user_id=user_id,
                user_id_snapshot=user_id,
                provider="eastmoney_gm",
                environment="simulation",
                professional_eligibility_confirmed=(
                    professional_eligibility_confirmed
                ),
                broker_simulation_permission_confirmed=(
                    broker_simulation_permission_confirmed
                ),
                filing_reference_ciphertext=_encrypt(
                    filing_reference.strip()
                ),
                evidence_document_sha256=(
                    evidence_document_sha256.lower()
                ),
                implementation_sha256=implementation_sha256(),
                reviewed_by_user_id=reviewed_by_user_id,
                reviewed_by_user_id_snapshot=reviewed_by_user_id,
                effective_at=now,
            )
        )
    return {
        "id": profile_id,
        "provider": "eastmoney_gm",
        "environment": "simulation",
        "implementationSha256": implementation_sha256(),
        "eligible": (
            professional_eligibility_confirmed
            and broker_simulation_permission_confirmed
        ),
    }


def bind_simulation(
    *,
    user_id: str,
    filing_profile_id: str,
    account_id: str,
    strategy_id: str,
) -> dict[str, Any]:
    if not account_id.strip() or not strategy_id.strip():
        raise ValueError("官方仿真账户和策略 ID 不能为空")
    if (
        not settings.emt_enabled
        or settings.emt_simulation_confirmation
        != "I_HAVE_SELECTED_EASTMONEY_SIMULATION_ACCOUNT"
        or account_id.strip() != settings.emt_account_id.strip()
        or strategy_id.strip() != settings.emt_strategy_id.strip()
    ):
        raise ValueError("绑定必须与显式启用的 EMT 仿真配置完全一致")
    with SessionLocal.begin() as session:
        profile = session.get(BrokerFilingProfile, filing_profile_id)
        if (
            profile is None
            or profile.user_id != user_id
            or profile.invalidated_at is not None
            or not profile.professional_eligibility_confirmed
            or not profile.broker_simulation_permission_confirmed
            or profile.implementation_sha256 != implementation_sha256()
        ):
            raise ValueError("报备档案无效或实现已发生变化")
        existing = session.execute(
            select(BrokerBinding).where(
                BrokerBinding.user_id == user_id,
                BrokerBinding.invalidated_at.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        values = {
            "filing_profile_id": profile.id,
            "provider": "eastmoney_gm",
            "environment": "simulation",
            "account_id_ciphertext": _encrypt(account_id.strip()),
            "account_id_sha256": hashlib.sha256(
                account_id.strip().encode()
            ).hexdigest(),
            "strategy_id_ciphertext": _encrypt(strategy_id.strip()),
            "status": "awaiting_bridge",
        }
        if existing is not None:
            existing.invalidated_at = _now()
            existing.status = "invalidated"
        binding = BrokerBinding(
            id=str(uuid4()),
            user_id=user_id,
            user_id_snapshot=user_id,
            **values,
        )
        session.add(binding)
        session.flush()
        return {
            "id": binding.id,
            "provider": binding.provider,
            "environment": binding.environment,
            "status": binding.status,
        }


def claim_bridge(
    binding_id: str,
    *,
    instance_id: str,
    sdk_version: str,
) -> dict[str, Any]:
    now = _now()
    with SessionLocal.begin() as session:
        binding = session.execute(
            select(BrokerBinding)
            .where(BrokerBinding.id == binding_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            binding is None
            or binding.environment != "simulation"
            or binding.invalidated_at is not None
        ):
            raise ValueError("官方仿真绑定不存在")
        account_id = str(_decrypt(binding.account_id_ciphertext))
        strategy_id = str(_decrypt(binding.strategy_id_ciphertext))
        if (
            not settings.emt_enabled
            or settings.emt_simulation_confirmation
            != "I_HAVE_SELECTED_EASTMONEY_SIMULATION_ACCOUNT"
            or account_id != settings.emt_account_id
            or strategy_id != settings.emt_strategy_id
        ):
            raise ValueError("EMT bridge 配置与仿真绑定不一致")
        if (
            binding.bridge_instance_id
            and binding.bridge_instance_id != instance_id
            and binding.bridge_lease_expires_at
            and _aware(binding.bridge_lease_expires_at) > now
        ):
            raise ValueError("已有 EMT bridge 持有租约")
        binding.bridge_instance_id = instance_id
        binding.bridge_lease_expires_at = now + BRIDGE_LEASE
        binding.last_heartbeat_at = now
        binding.sdk_version = sdk_version[:32]
        binding.status = "read_only_connected"
        return {
            "bindingId": binding.id,
            "accountId": account_id,
            "strategyId": strategy_id,
            "leaseExpiresAt": binding.bridge_lease_expires_at.isoformat(),
        }


def enqueue_rehearsal_order(
    *,
    user: User,
    binding_id: str,
    idempotency_key: str,
    code: str,
    side: str,
    qty: int,
    limit_price: float,
    step_up_token: str,
) -> dict[str, Any]:
    user_id = str(user.id)
    if side not in {"buy", "sell"}:
        raise ValueError("委托方向无效")
    if qty <= 0 or qty % 100:
        raise ValueError("仿真委托数量必须为 100 股整数倍")
    rounded_price = float(
        Decimal(str(limit_price)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )
    if (
        rounded_price <= 0
        or qty * rounded_price > REHEARSAL_MAX_NOTIONAL
    ):
        raise ValueError("M7 单笔仿真演练名义金额不得超过 2 万元")
    if not 8 <= len(idempotency_key) <= 64:
        raise ValueError("幂等键长度必须在 8–64")
    now = _now()
    request = {
        "bindingId": binding_id,
        "code": code,
        "side": side,
        "orderType": "limit",
        "price": rounded_price,
        "qty": qty,
        "environment": "simulation",
    }
    order_id = str(uuid4())
    with SessionLocal() as session:
        existing = session.execute(
            select(BrokerOrder).where(
                BrokerOrder.user_id == user_id,
                BrokerOrder.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.request_sha256 != _hash(request):
                raise ValueError("幂等键已绑定不同委托")
            return _order(existing)
    try:
        with SessionLocal.begin() as session:
            locked_user = session.execute(
                select(User)
                .where(User.id == user_id)
                .with_for_update()
            ).scalar_one_or_none()
            if locked_user is None:
                raise ValueError("用户不存在")
            step_up.consume(
                session,
                user=locked_user,
                token=step_up_token,
                purpose="submit_broker_simulation",
            )
            binding = session.get(BrokerBinding, binding_id)
            risk_profile = session.execute(
                select(PortfolioRiskProfile)
                .where(PortfolioRiskProfile.user_id == user_id)
                .with_for_update()
            ).scalar_one_or_none()
            filing_profile = (
                session.get(
                    BrokerFilingProfile, binding.filing_profile_id
                )
                if binding is not None
                else None
            )
            if (
                binding is None
                or binding.user_id != user_id
                or binding.environment != "simulation"
                or binding.status != "read_only_connected"
                or risk_profile is None
                or risk_profile.kill_switch_active
                or not binding.bridge_lease_expires_at
                or _aware(binding.bridge_lease_expires_at) <= now
                or filing_profile is None
                or filing_profile.invalidated_at is not None
                or filing_profile.implementation_sha256
                != implementation_sha256()
            ):
                raise ValueError("EMT 仿真绑定、租约或报备证据无效")
            session.add(
                BrokerOrder(
                    id=order_id,
                    user_id=user_id,
                    user_id_snapshot=user_id,
                    binding_id=binding_id,
                    decision_override_id=None,
                    idempotency_key=idempotency_key,
                    code=code,
                    side=side,
                    order_type="limit",
                    price=rounded_price,
                    qty=qty,
                    status="blocked_account_type",
                    request_sha256=_hash(request),
                    attempts=0,
                    next_attempt_at=now,
                )
            )
            session.flush()
    except IntegrityError:
        with SessionLocal() as session:
            existing = session.execute(
                select(BrokerOrder).where(
                    BrokerOrder.user_id_snapshot == user_id,
                    BrokerOrder.idempotency_key == idempotency_key,
                )
            ).scalar_one()
            if existing.request_sha256 != _hash(request):
                raise ValueError("幂等键已绑定不同委托") from None
            return _order(existing)
    with SessionLocal() as session:
        return _order(session.get(BrokerOrder, order_id))


def binding_for_user(user_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.execute(
            select(BrokerBinding).where(
                BrokerBinding.user_id == user_id,
                BrokerBinding.invalidated_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        latest_rehearsal = session.execute(
            select(BrokerRehearsalRun)
            .where(BrokerRehearsalRun.binding_id == row.id)
            .order_by(BrokerRehearsalRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return {
            "id": row.id,
            "provider": row.provider,
            "environment": row.environment,
            "status": row.status,
            "sdkVersion": row.sdk_version,
            "lastHeartbeatAt": (
                row.last_heartbeat_at.isoformat()
                if row.last_heartbeat_at
                else None
            ),
            "officialRehearsalPassed": bool(
                latest_rehearsal and latest_rehearsal.passed
            ),
            "liveTradingEnabled": False,
        }


def list_orders(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(BrokerOrder)
            .where(BrokerOrder.user_id == user_id)
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_order(row) for row in rows]


def revoke_for_kill_switch(user_id: str) -> int:
    with SessionLocal() as session:
        binding_ids = session.execute(
            select(BrokerOrder.binding_id)
            .where(
                BrokerOrder.user_id == user_id,
                BrokerOrder.status.in_(["queued", "sending"]),
            )
            .distinct()
        ).scalars().all()
    revoked = 0
    for binding_id in binding_ids:
        with SessionLocal.begin() as session:
            session.execute(
                select(BrokerBinding)
                .where(BrokerBinding.id == binding_id)
                .with_for_update()
            ).scalar_one()
            rows = session.execute(
                select(BrokerOrder)
                .where(
                    BrokerOrder.binding_id == binding_id,
                    BrokerOrder.user_id == user_id,
                    BrokerOrder.status.in_(["queued", "sending"]),
                )
                .with_for_update()
            ).scalars().all()
            for row in rows:
                row.status = (
                    "revoked_by_kill_switch"
                    if row.status == "queued"
                    else "uncertain"
                )
                row.claim_token = None
                row.claim_started_at = None
                _append_event(
                    session,
                    binding_id=binding_id,
                    broker_order_id=row.id,
                    source_event_id=(
                        f"kill-switch:{row.id}:{row.status}"
                    ),
                    event_type="kill_switch_revocation",
                    payload={
                        "status": row.status,
                        "reason": "kill_switch",
                    },
                    occurred_at=_now(),
                )
            revoked += len(rows)
    return revoked


def _order(row: BrokerOrder) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "side": row.side,
        "orderType": row.order_type,
        "price": row.price,
        "qty": row.qty,
        "status": row.status,
        "brokerClientOrderId": row.broker_cl_ord_id,
        "attempts": row.attempts,
        "createdAt": row.created_at.isoformat(),
        "environment": "simulation",
    }


def _assert_bridge(
    binding: BrokerBinding, instance_id: str, now: datetime
) -> str:
    if (
        binding.invalidated_at is not None
        or binding.user_id is None
        or binding.status not in {
            "read_only_connected",
            "connected",
            "rehearsal_passed",
            "rehearsal_failed",
        }
        or binding.bridge_instance_id != instance_id
        or not binding.bridge_lease_expires_at
        or _aware(binding.bridge_lease_expires_at) <= now
    ):
        raise ValueError("EMT bridge 租约无效")
    return str(_decrypt(binding.account_id_ciphertext))


def _filing_valid(session, binding: BrokerBinding) -> bool:
    filing = session.get(
        BrokerFilingProfile, binding.filing_profile_id
    )
    return bool(
        filing
        and filing.invalidated_at is None
        and filing.professional_eligibility_confirmed
        and filing.broker_simulation_permission_confirmed
        and filing.implementation_sha256 == implementation_sha256()
    )


def _consume_rate(session, binding_id: str, now: datetime) -> bool:
    row = session.execute(
        select(BrokerRateWindow)
        .where(BrokerRateWindow.binding_id == binding_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        session.add(
            BrokerRateWindow(
                binding_id=binding_id,
                window_started_at=now,
                order_count=1,
            )
        )
        return True
    started = _aware(row.window_started_at)
    if now - started >= timedelta(seconds=1):
        row.window_started_at = now
        row.order_count = 1
        return True
    if row.order_count >= settings.emt_max_orders_per_second:
        return False
    row.order_count += 1
    return True


def _claim_next_order(
    binding_id: str,
    *,
    instance_id: str,
) -> tuple[BrokerOrderRequest, str] | None:
    now = _now()
    token = str(uuid4())
    with SessionLocal.begin() as session:
        binding_preview = session.get(BrokerBinding, binding_id)
        if binding_preview is None or binding_preview.user_id is None:
            raise ValueError("EMT 仿真绑定不存在")
        user_id = binding_preview.user_id
        user = session.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        profile = session.execute(
            select(PortfolioRiskProfile)
            .where(PortfolioRiskProfile.user_id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        binding = session.execute(
            select(BrokerBinding)
            .where(BrokerBinding.id == binding_id)
            .with_for_update()
        ).scalar_one_or_none()
        if binding is None:
            raise ValueError("EMT 仿真绑定不存在")
        if (
            user is None
            or profile is None
            or profile.kill_switch_active
            or not _filing_valid(session, binding)
        ):
            queued = session.execute(
                select(BrokerOrder)
                .where(
                    BrokerOrder.binding_id == binding_id,
                    BrokerOrder.status == "queued",
                )
                .with_for_update()
            ).scalars().all()
            for order in queued:
                order.status = (
                    "revoked_by_kill_switch"
                    if profile is not None
                    and profile.kill_switch_active
                    else "blocked_filing"
                )
                _append_event(
                    session,
                    binding_id=binding_id,
                    broker_order_id=order.id,
                    source_event_id=(
                        f"authorization:{order.id}:{order.status}"
                    ),
                    event_type="authorization_revoked",
                    payload={
                        "status": order.status,
                        "reason": order.status,
                    },
                    occurred_at=now,
                )
            return None
        account_id = _assert_bridge(binding, instance_id, now)
        stale = session.execute(
            select(BrokerOrder)
            .where(
                BrokerOrder.binding_id == binding_id,
                BrokerOrder.status == "sending",
                BrokerOrder.claim_started_at
                <= now - SEND_UNCERTAIN_AFTER,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for row in stale:
            row.status = "uncertain"
            row.claim_token = None
            row.claim_started_at = None
        statement = (
            select(BrokerOrder)
            .where(
                BrokerOrder.binding_id == binding_id,
                BrokerOrder.status == "queued",
                BrokerOrder.next_attempt_at <= now,
            )
            .order_by(BrokerOrder.created_at)
            .limit(1)
        )
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        else:
            statement = statement.with_for_update()
        order = session.execute(statement).scalar_one_or_none()
        if order is None:
            return None
        if not _consume_rate(session, binding_id, now):
            return None
        order.status = "sending"
        order.claim_token = token
        order.claim_started_at = now
        order.last_send_started_at = now
        order.attempts += 1
        return (
            BrokerOrderRequest(
                client_order_id=order.id,
                symbol=order.code,
                side=order.side,
                order_type=order.order_type,
                qty=order.qty,
                price=order.price,
                account_id=account_id,
            ),
            token,
        )


def _append_event(
    session,
    *,
    binding_id: str,
    broker_order_id: str | None,
    source_event_id: str,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> None:
    if session.get_bind().dialect.name == "postgresql":
        lock_key = int.from_bytes(
            hashlib.sha256(binding_id.encode()).digest()[:8],
            "big",
            signed=True,
        )
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    existing = session.execute(
        select(BrokerEvent.id).where(
            BrokerEvent.binding_id == binding_id,
            BrokerEvent.source_event_id == source_event_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    previous = session.execute(
        select(BrokerEvent)
        .where(BrokerEvent.binding_id == binding_id)
        .order_by(BrokerEvent.created_at.desc(), BrokerEvent.id.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()
    payload_sha256 = _hash(payload)
    previous_hash = previous.event_sha256 if previous else None
    event_sha256 = _hash(
        {
            "bindingId": binding_id,
            "brokerOrderId": broker_order_id,
            "sourceEventId": source_event_id,
            "eventType": event_type,
            "payloadSha256": payload_sha256,
            "previousEventSha256": previous_hash,
            "occurredAt": occurred_at.isoformat(),
        }
    )
    session.add(
        BrokerEvent(
            id=str(uuid4()),
            binding_id=binding_id,
            broker_order_id=broker_order_id,
            source_event_id=source_event_id,
            event_type=event_type,
            payload_ciphertext=_encrypt(payload),
            payload_sha256=payload_sha256,
            previous_event_sha256=previous_hash,
            event_sha256=event_sha256,
            occurred_at=occurred_at,
        )
    )


def publish_submit_result(
    order_id: str,
    *,
    claim_token: str,
    response: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _now()
    with SessionLocal.begin() as session:
        order = session.execute(
            select(BrokerOrder)
            .where(
                BrokerOrder.id == order_id,
                BrokerOrder.claim_token == claim_token,
                BrokerOrder.status == "sending",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if order is None:
            raise ValueError("旧 bridge 不得发布委托结果")
        safe_response = _safe(response or {})
        broker_id = str(safe_response.get("cl_ord_id") or "")
        normalized = str(
            safe_response.get("_normalizedStatus") or "unknown"
        )
        if not broker_id:
            order.status = "uncertain"
        elif normalized in {
            "acked",
            "partially_filled",
            "filled",
            "cancelled",
            "rejected",
        }:
            order.status = normalized
            order.broker_cl_ord_id = broker_id
        else:
            order.status = "acked"
            order.broker_cl_ord_id = broker_id
        order.response_ciphertext = _encrypt(safe_response)
        order.claim_token = None
        order.claim_started_at = None
        source_id = (
            f"submit:{broker_id}"
            if broker_id
            else f"uncertain:{order.id}:{order.attempts}"
        )
        _append_event(
            session,
            binding_id=order.binding_id,
            broker_order_id=order.id,
            source_event_id=source_id,
            event_type="submit_result",
            payload=safe_response,
            occurred_at=now,
        )
        session.flush()
        return _order(order)


def process_one(
    binding_id: str,
    *,
    instance_id: str,
    adapter: BrokerAdapter,
) -> dict[str, Any] | None:
    if not adapter.simulation_account_verified:
        raise ValueError(
            "官方 gm.api 未提供可机器验证的仿真账户类型，发送路径保持关闭"
        )
    claimed = _claim_next_order(
        binding_id, instance_id=instance_id
    )
    if claimed is None:
        return None
    request, token = claimed
    with SessionLocal.begin() as session:
        order_preview = session.get(
            BrokerOrder, request.client_order_id
        )
        binding_preview = (
            session.get(BrokerBinding, order_preview.binding_id)
            if order_preview is not None
            else None
        )
        user_id = (
            binding_preview.user_id if binding_preview is not None else None
        )
        if user_id is not None:
            session.execute(
                select(User).where(User.id == user_id).with_for_update()
            ).scalar_one_or_none()
            profile = session.execute(
                select(PortfolioRiskProfile)
                .where(PortfolioRiskProfile.user_id == user_id)
                .with_for_update()
            ).scalar_one_or_none()
        else:
            profile = None
        order = session.execute(
            select(BrokerOrder)
            .where(
                BrokerOrder.id == request.client_order_id,
                BrokerOrder.claim_token == token,
                BrokerOrder.status == "sending",
            )
            .with_for_update()
        ).scalar_one()
        binding = session.execute(
            select(BrokerBinding)
            .where(BrokerBinding.id == order.binding_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            binding is None
            or binding.user_id is None
            or profile is None
            or profile.kill_switch_active
            or not _filing_valid(session, binding)
        ):
            order.status = (
                "revoked_by_kill_switch"
                if profile is not None and profile.kill_switch_active
                else "blocked_filing"
            )
            order.claim_token = None
            order.claim_started_at = None
            _append_event(
                session,
                binding_id=order.binding_id,
                broker_order_id=order.id,
                source_event_id=(
                    f"authorization:{order.id}:{order.status}"
                ),
                event_type="authorization_revoked",
                payload={
                    "status": order.status,
                    "reason": order.status,
                },
                occurred_at=_now(),
            )
            return _order(order)
    try:
        response = adapter.submit_order(request)
    except Exception:
        return publish_submit_result(
            request.client_order_id,
            claim_token=token,
            response=None,
        )
    return publish_submit_result(
        request.client_order_id,
        claim_token=token,
        response=response,
    )


def reconcile(
    binding_id: str,
    *,
    instance_id: str,
    adapter: BrokerAdapter,
) -> dict[str, Any]:
    now = _now()
    with SessionLocal() as session:
        binding = session.get(BrokerBinding, binding_id)
        if binding is None:
            raise ValueError("EMT 仿真绑定不存在")
        account_id = _assert_bridge(binding, instance_id, now)
    snapshot = {
        "capturedAt": now.isoformat(),
        "sdkVersion": adapter.sdk_version,
        "cash": adapter.account_snapshot(account_id),
        "positions": adapter.positions(account_id),
        "orders": adapter.orders(account_id),
        "executions": adapter.executions(account_id),
    }
    remote_by_id = {
        str(row.get("cl_ord_id")): row
        for row in snapshot["orders"]
        if row.get("cl_ord_id")
    }
    mismatches = []
    cash = snapshot["cash"]
    if (
        str(cash.get("account_id") or "") != account_id
        or not isinstance(cash.get("nav"), (int, float))
        or float(cash["nav"]) < 0
        or not isinstance(cash.get("available"), (int, float))
        or float(cash["available"]) < 0
    ):
        mismatches.append({"type": "invalid_cash_snapshot"})
    for position in snapshot["positions"]:
        if (
            str(position.get("account_id") or "") != account_id
            or not position.get("symbol")
            or int(position.get("volume") or -1) < 0
        ):
            mismatches.append(
                {
                    "type": "invalid_position_snapshot",
                    "positionHash": _hash(position),
                }
            )
    with SessionLocal.begin() as session:
        binding = session.execute(
            select(BrokerBinding)
            .where(BrokerBinding.id == binding_id)
            .with_for_update()
        ).scalar_one()
        _assert_bridge(binding, instance_id, _now())
        local_orders = session.execute(
            select(BrokerOrder).where(
                BrokerOrder.binding_id == binding_id
            )
        ).scalars().all()
        local_ids = {
            row.broker_cl_ord_id
            for row in local_orders
            if row.broker_cl_ord_id
        }
        untracked_remote = {
            remote_id: remote
            for remote_id, remote in remote_by_id.items()
            if remote_id not in local_ids
        }
        for order in local_orders:
            if order.status != "uncertain" or order.broker_cl_ord_id:
                continue
            candidates = [
                (remote_id, remote)
                for remote_id, remote in untracked_remote.items()
                if remote.get("_normalizedCode") == order.code
                and remote.get("_normalizedSide") == order.side
                and remote.get("_normalizedQty") == order.qty
                and _parse_time(remote.get("created_at")) is not None
                and order.last_send_started_at is not None
                and abs(
                    (
                        _parse_time(remote["created_at"])
                        - _aware(order.last_send_started_at)
                    ).total_seconds()
                )
                <= 120
            ]
            if len(candidates) == 1:
                remote_id, remote = candidates[0]
                order.broker_cl_ord_id = remote_id
                order.status = str(
                    remote.get("_normalizedStatus") or "acked"
                )
                local_ids.add(remote_id)
                untracked_remote.pop(remote_id, None)
                _append_event(
                    session,
                    binding_id=binding_id,
                    broker_order_id=order.id,
                    source_event_id=f"recovered:{remote_id}",
                    event_type="uncertain_recovered",
                    payload=remote,
                    occurred_at=now,
                )
            elif len(candidates) > 1:
                mismatches.append(
                    {
                        "type": "ambiguous_uncertain_submit",
                        "localOrderId": order.id,
                    }
                )
        for order in local_orders:
            if not order.broker_cl_ord_id:
                if order.status == "uncertain":
                    mismatches.append(
                        {
                            "type": "uncertain_submit",
                            "localOrderId": order.id,
                        }
                    )
                continue
            remote = remote_by_id.get(order.broker_cl_ord_id)
            if remote is None:
                if order.status not in {"filled", "cancelled", "rejected"}:
                    mismatches.append(
                        {
                            "type": "local_order_missing_remote",
                            "localOrderId": order.id,
                        }
                    )
                continue
            normalized = remote.get("_normalizedStatus")
            if normalized in {
                "acked",
                "partially_filled",
                "filled",
                "cancelled",
                "rejected",
            }:
                order.status = normalized
            else:
                mismatches.append(
                    {
                        "type": "unknown_remote_order_status",
                        "brokerClientOrderIdHash": hashlib.sha256(
                            order.broker_cl_ord_id.encode()
                        ).hexdigest(),
                    }
                )
            source_id = "order:" + _hash(
                {
                    "clOrdId": order.broker_cl_ord_id,
                    "status": remote.get("status"),
                    "filledVolume": remote.get("filled_volume"),
                    "updatedAt": remote.get("updated_at"),
                }
            )
            _append_event(
                session,
                binding_id=binding_id,
                broker_order_id=order.id,
                source_event_id=source_id,
                event_type="order_snapshot",
                payload=remote,
                occurred_at=now,
            )
        local_by_broker_id = {
            order.broker_cl_ord_id: order
            for order in local_orders
            if order.broker_cl_ord_id
        }
        for execution in snapshot["executions"]:
            execution_id = str(execution.get("exec_id") or "")
            broker_id = str(execution.get("cl_ord_id") or "")
            order = local_by_broker_id.get(broker_id)
            if not execution_id or order is None:
                mismatches.append(
                    {
                        "type": "untracked_execution",
                        "executionHash": _hash(execution),
                    }
                )
                continue
            _append_event(
                session,
                binding_id=binding_id,
                broker_order_id=order.id,
                source_event_id=f"execution:{execution_id}",
                event_type="execution",
                payload=execution,
                occurred_at=now,
            )
        for remote_id in sorted(set(remote_by_id) - local_ids):
            mismatches.append(
                {
                    "type": "untracked_remote_order",
                    "brokerClientOrderIdHash": hashlib.sha256(
                        remote_id.encode()
                    ).hexdigest(),
                }
            )
        evidence = {
            "capturedAt": now.isoformat(),
            "snapshotSha256": _hash(snapshot),
            "mismatches": mismatches,
        }
        reconciliation_id = str(uuid4())
        session.add(
            BrokerReconciliation(
                id=reconciliation_id,
                binding_id=binding_id,
                status="clean" if not mismatches else "mismatch",
                snapshot_ciphertext=_encrypt(snapshot),
                snapshot_sha256=_hash(snapshot),
                mismatch_count=len(mismatches),
                evidence_json=dump_envelope(evidence),
            )
        )
    return {
        "id": reconciliation_id,
        "status": "clean" if not mismatches else "mismatch",
        "mismatchCount": len(mismatches),
        "snapshotSha256": _hash(snapshot),
    }


def record_rehearsal(
    binding_id: str,
    *,
    instance_id: str,
    adapter: emt.OfficialEmtAdapter,
) -> dict[str, Any]:
    runtime_evidence = adapter.runtime_evidence()
    sdk_version = adapter.sdk_version
    now = _now()
    with SessionLocal.begin() as session:
        binding = session.execute(
            select(BrokerBinding)
            .where(BrokerBinding.id == binding_id)
            .with_for_update()
        ).scalar_one_or_none()
        if binding is None:
            raise ValueError("EMT 仿真绑定不存在")
        _assert_bridge(binding, instance_id, now)
        latest_reconciliation = session.execute(
            select(BrokerReconciliation)
            .where(BrokerReconciliation.binding_id == binding_id)
            .order_by(BrokerReconciliation.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        order_count = session.scalar(
            select(func.count(BrokerOrder.id)).where(
                BrokerOrder.binding_id == binding_id
            )
        )
        recovered_count = session.scalar(
            select(func.count(BrokerEvent.id)).where(
                BrokerEvent.binding_id == binding_id,
                BrokerEvent.event_type == "uncertain_recovered",
            )
        )
        rate_window = session.get(BrokerRateWindow, binding_id)
        account_id = str(_decrypt(binding.account_id_ciphertext))
        strategy_id = str(_decrypt(binding.strategy_id_ciphertext))
        checks = {
            "officialSdkLoaded": runtime_evidence["module"] == "gm.api",
            "simulationAccount": (
                adapter.simulation_account_verified
                and
                account_id == settings.emt_account_id
                and strategy_id == settings.emt_strategy_id
                and settings.emt_simulation_confirmation
                == "I_HAVE_SELECTED_EASTMONEY_SIMULATION_ACCOUNT"
            ),
            "idempotency": bool(order_count),
            "rateLimit": bool(
                rate_window
                and rate_window.order_count
                <= settings.emt_max_orders_per_second
            ),
            "disconnectRecovery": bool(recovered_count),
            "cleanReconciliation": bool(
                latest_reconciliation
                and latest_reconciliation.status == "clean"
            ),
        }
        passed = (
            all(checks.values())
            and latest_reconciliation is not None
            and latest_reconciliation.status == "clean"
            and sdk_version != "unknown"
            and binding.sdk_version == sdk_version
        )
        evidence = {
            "bindingId": binding_id,
            "sdkVersion": sdk_version,
            "implementationSha256": implementation_sha256(),
            "checks": checks,
            "runtimeEvidence": runtime_evidence,
            "reconciliationId": (
                latest_reconciliation.id
                if latest_reconciliation
                else None
            ),
            "recordedAt": now.isoformat(),
        }
        run_id = str(uuid4())
        session.add(
            BrokerRehearsalRun(
                id=run_id,
                binding_id=binding_id,
                sdk_version=sdk_version,
                implementation_sha256=implementation_sha256(),
                checks_json=dump_envelope(evidence),
                evidence_sha256=_hash(evidence),
                passed=passed,
            )
        )
        binding.status = (
            "rehearsal_passed" if passed else "rehearsal_failed"
        )
    return {
        "id": run_id,
        "passed": passed,
        "officialTerminalVerified": passed,
    }
