"""回测运行 ORM（Phase 4 M3）。

持久化每次回测的配置 / 状态 / 绩效 / 权益曲线 / 成交，供历史回看与（M4）AI 点评复用。
JSON 字段为 PortableJSON（Postgres JSONB）；载荷带 schemaVersion 信封（见 ``json_payload``）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    strategy_type: Mapped[str] = mapped_column(String(32), default="")
    # completed / failed / data_corrupt
    status: Mapped[str] = mapped_column(String(16), default="completed")
    config_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    metrics_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    equity_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    trades_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    data_quality_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        PortableJSON, nullable=True
    )
    engine: Mapped[str] = mapped_column(String(16), default="native")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
