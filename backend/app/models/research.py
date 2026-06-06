"""自主深度研究报告 ORM 模型（Phase 2 对话中枢增量）。

持久化每次深度研究的问题、研究计划（子问题）、分步轨迹（含工具调用）与最终报告，
便于事后回看/复盘，并为 Phase 3 的 AI 复盘复用同一套"可观测研究记录"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    question: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(16), default="ready")  # generating/ready/partial/failed
    content: Mapped[str] = mapped_column(Text, default="")            # 报告正文（Markdown）
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # 子问题列表(JSON)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 分步轨迹[{label,tools}](JSON)
    model: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
