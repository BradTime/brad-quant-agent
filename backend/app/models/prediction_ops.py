from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class PredictionOpsJob(Base):
    __tablename__ = "prediction_ops_jobs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_prediction_ops_job_idempotency",
        ),
        Index(
            "ix_prediction_ops_jobs_status_next",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by_user_id_snapshot: Mapped[str] = mapped_column(String(36))
    job_type: Mapped[str] = mapped_column(String(24))
    scheduled_for: Mapped[date] = mapped_column(Date)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24))
    payload_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    result_json: Mapped[
        dict[str, Any] | list[Any] | None
    ] = mapped_column(PortableJSON)
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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


__all__ = ["PredictionOpsJob"]
