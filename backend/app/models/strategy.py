"""Persisted user strategies backed only by the built-in strategy catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func, text
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
