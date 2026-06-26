"""回测运行 ORM（Phase 4 M3）。

持久化每次回测的配置 / 状态 / 绩效 / 权益曲线 / 成交，供历史回看与（M4）AI 点评复用。
大字段以 JSON 文本存（MVP 足够；权益/成交超量后可转列存 DuckDB/Parquet）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    strategy_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="completed")  # completed / failed
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    equity_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    trades_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_quality_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str] = mapped_column(String(16), default="native")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
