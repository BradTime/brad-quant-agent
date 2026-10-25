from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class DecisionRun(Base):
    __tablename__ = "decision_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id_snapshot",
            "as_of",
            "request_sha256",
            name="uq_decision_run_user_date_request",
        ),
        Index("ix_decision_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_id_snapshot: Mapped[str] = mapped_column(String(36))
    as_of: Mapped[date] = mapped_column(Date)
    request_sha256: Mapped[str] = mapped_column(String(64))
    allocation_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "portfolio_allocation_decisions.id",
            ondelete="RESTRICT",
        )
    )
    protocol_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24))
    current_stage: Mapped[str] = mapped_column(String(32))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    severe_disagreement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    event_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    terminal_event_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DecisionEvent(Base):
    __tablename__ = "decision_events"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_decision_event_run_sequence",
        ),
        UniqueConstraint(
            "event_sha256",
            name="uq_decision_event_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("decision_runs.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(32))
    input_sha256: Mapped[str] = mapped_column(String(64))
    output_sha256: Mapped[str] = mapped_column(String(64))
    previous_event_sha256: Mapped[str | None] = mapped_column(String(64))
    event_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["DecisionEvent", "DecisionRun"]
