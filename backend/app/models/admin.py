"""Durable, sanitized privilege-change audit records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminPrivilegeAudit(Base):
    __tablename__ = "admin_privilege_audits"
    __table_args__ = (
        Index("ix_admin_privilege_audits_target_created", "target_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_user_id_snapshot: Mapped[str] = mapped_column(String(36), nullable=False)
    prior_role: Mapped[str] = mapped_column(String(16), nullable=False)
    new_role: Mapped[str] = mapped_column(String(16), nullable=False)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
