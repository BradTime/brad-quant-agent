"""盘前早报（Phase 2）ORM 模型。

每份早报落库时一并保存生成所依据的数据快照（``data_pack_json``），
便于事后复盘与 PIT 复查（避免"凭记忆"或来源不可追溯）。
``user_id`` 可为空：空表示系统级全局早报（调度器每日生成），
非空表示某用户基于其自选股生成的个性化早报。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MorningBrief(Base):
    __tablename__ = "morning_briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), default="ready")  # generating/ready/failed
    title: Mapped[str] = mapped_column(String(160), default="")
    content: Mapped[str] = mapped_column(Text, default="")           # 早报正文（Markdown）
    data_pack_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 依据数据快照(JSON)
    source_note: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
