from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class BrokerFilingProfile(Base):
    __tablename__ = "broker_filing_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    user_id_snapshot: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(24))
    environment: Mapped[str] = mapped_column(String(16))
    professional_eligibility_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    broker_simulation_permission_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    filing_reference_ciphertext: Mapped[str] = mapped_column(Text)
    evidence_document_sha256: Mapped[str] = mapped_column(String(64))
    implementation_sha256: Mapped[str] = mapped_column(String(64))
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by_user_id_snapshot: Mapped[str] = mapped_column(String(36))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerBinding(Base):
    __tablename__ = "broker_bindings"
    __table_args__ = (
        Index(
            "uq_broker_binding_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("invalidated_at IS NULL"),
            sqlite_where=text("invalidated_at IS NULL"),
        ),
        Index(
            "uq_broker_binding_active_account",
            "provider",
            "account_id_sha256",
            unique=True,
            postgresql_where=text("invalidated_at IS NULL"),
            sqlite_where=text("invalidated_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_id_snapshot: Mapped[str] = mapped_column(String(36))
    filing_profile_id: Mapped[str] = mapped_column(
        ForeignKey("broker_filing_profiles.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(24))
    environment: Mapped[str] = mapped_column(String(16))
    account_id_ciphertext: Mapped[str] = mapped_column(Text)
    account_id_sha256: Mapped[str] = mapped_column(String(64))
    strategy_id_ciphertext: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    sdk_version: Mapped[str | None] = mapped_column(String(32))
    bridge_instance_id: Mapped[str | None] = mapped_column(String(64))
    bridge_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BrokerOrder(Base):
    __tablename__ = "broker_orders"
    __table_args__ = (
        UniqueConstraint(
            "user_id_snapshot",
            "idempotency_key",
            name="uq_broker_order_user_idempotency",
        ),
        Index("ix_broker_orders_status_next", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_id_snapshot: Mapped[str] = mapped_column(String(36))
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("broker_bindings.id", ondelete="RESTRICT")
    )
    decision_override_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_overrides.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8))
    price: Mapped[float | None] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    request_sha256: Mapped[str] = mapped_column(String(64))
    broker_cl_ord_id: Mapped[str | None] = mapped_column(String(128))
    response_ciphertext: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    claim_token: Mapped[str | None] = mapped_column(String(36))
    claim_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_send_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BrokerRateWindow(Base):
    __tablename__ = "broker_rate_windows"

    binding_id: Mapped[str] = mapped_column(
        ForeignKey("broker_bindings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    order_count: Mapped[int] = mapped_column(Integer)


class BrokerEvent(Base):
    __tablename__ = "broker_events"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "source_event_id",
            name="uq_broker_event_binding_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("broker_bindings.id", ondelete="RESTRICT"), index=True
    )
    broker_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_orders.id", ondelete="RESTRICT")
    )
    source_event_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(32))
    payload_ciphertext: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    previous_event_sha256: Mapped[str | None] = mapped_column(String(64))
    event_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerReconciliation(Base):
    __tablename__ = "broker_reconciliations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("broker_bindings.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    snapshot_ciphertext: Mapped[str] = mapped_column(Text)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    mismatch_count: Mapped[int] = mapped_column(Integer)
    evidence_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BrokerRehearsalRun(Base):
    __tablename__ = "broker_rehearsal_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("broker_bindings.id", ondelete="RESTRICT"), index=True
    )
    sdk_version: Mapped[str] = mapped_column(String(32))
    implementation_sha256: Mapped[str] = mapped_column(String(64))
    checks_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "BrokerBinding",
    "BrokerEvent",
    "BrokerFilingProfile",
    "BrokerOrder",
    "BrokerReconciliation",
    "BrokerRehearsalRun",
    "BrokerRateWindow",
]
