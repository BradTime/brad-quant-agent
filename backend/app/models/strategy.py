"""Strategy heads and immutable executable definition versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    builtin_type: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="builtin", server_default="builtin"
    )
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    protocol_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="signal-v1", server_default="signal-v1"
    )
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    params_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'{}'")
    )
    # draft / active / disabled / data_corrupt
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "definition_type IN ('builtin','custom_python')",
            name="ck_strategies_definition_type",
        ),
        CheckConstraint("current_version >= 1", name="ck_strategies_current_version"),
    )


class StrategyVersion(Base):
    """Immutable strategy definition snapshot."""

    __tablename__ = "strategy_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_type: Mapped[str] = mapped_column(String(16), nullable=False)
    builtin_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    params_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    source_code: Mapped[str | None] = mapped_column(Text)
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "version", name="uq_strategy_versions_strategy_version"
        ),
        CheckConstraint("version >= 1", name="ck_strategy_versions_version"),
        CheckConstraint(
            "definition_type IN ('builtin','custom_python')",
            name="ck_strategy_versions_definition_type",
        ),
    )
