"""异步任务 ORM（回测网格等长任务，由 worker 认领）。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class BacktestJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestJob(Base):
    __tablename__ = "backtest_jobs"
    __table_args__ = (
        Index(
            "uq_backtest_jobs_active_full_a",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text(
                "kind = 'full_a' AND status IN ('queued','running')"
            ),
            sqlite_where=text(
                "kind = 'full_a' AND status IN ('queued','running')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'grid'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'queued'")
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    claim_token: Mapped[str | None] = mapped_column(String(36))
    request_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    result_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    progress_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
