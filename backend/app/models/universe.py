"""Materialized point-in-time A-share universe membership."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class UniverseMembershipDaily(Base):
    __tablename__ = "universe_membership_daily"
    __table_args__ = (
        Index(
            "ix_universe_membership_date_eligible",
            "trade_date",
            "eligible",
        ),
    )

    code: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("instruments.code", ondelete="RESTRICT"),
        primary_key=True,
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    average_amount: Mapped[float | None] = mapped_column(Numeric(24, 4))
    listing_sessions: Mapped[int | None] = mapped_column(Integer)
    rules_version: Mapped[str] = mapped_column(
        String(16), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UniverseSnapshotDaily(Base):
    __tablename__ = "universe_snapshot_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rules_version: Mapped[str] = mapped_column(String(16), primary_key=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    advancing_count: Mapped[int | None] = mapped_column(Integer)
    declining_count: Mapped[int | None] = mapped_column(Integer)
    filters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    membership_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
