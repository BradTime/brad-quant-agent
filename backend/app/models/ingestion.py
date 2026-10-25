"""Auditable per-symbol ingestion run snapshots."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'ready', 'partial', 'failed')",
            name="ck_ingestion_runs_status",
        ),
        Index(
            "ix_ingestion_runs_covering",
            "code",
            "start_date",
            "end_date",
            "started_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    datasets_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TushareBootstrapDailyManifest(Base):
    __tablename__ = "tushare_bootstrap_daily_manifests"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    daily_count: Mapped[int] = mapped_column(Integer)
    factor_count: Mapped[int] = mapped_column(Integer)
    daily_sha256: Mapped[str] = mapped_column(String(64))
    factor_sha256: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndustryMembershipSnapshot(Base):
    """Immutable evidence manifest for one effective-dated industry dataset."""

    __tablename__ = "industry_membership_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "taxonomy",
            "level",
            "as_of_date",
            name="uq_industry_membership_snapshot_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    taxonomy: Mapped[str] = mapped_column(String(16), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_floor: Mapped[date] = mapped_column(Date, nullable=False)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    persisted_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unknown_code_count: Mapped[int] = mapped_column(Integer, nullable=False)
    classification_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MoneyflowHistorySnapshot(Base):
    """Immutable manifest for a fixed-pool historical moneyflow dataset."""

    __tablename__ = "moneyflow_history_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "as_of_date",
            "start_date",
            "end_date",
            "codes_sha256",
            name="uq_moneyflow_history_snapshot_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    code_count: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    codes_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_policy: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
