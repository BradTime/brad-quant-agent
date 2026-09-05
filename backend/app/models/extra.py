"""Additional market datasets (Phase 0 完结): 资金流 / 财务摘要 / 龙虎榜 / 新闻公告。

All carry PIT audit columns (``source`` / ``fetched_at``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_AMOUNT = Numeric(24, 4)
_RATIO = Numeric(12, 4)


class CapitalFlow(Base):
    """个股资金流（按日）。"""

    __tablename__ = "capital_flows"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    main_net: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)        # 主力净流入额(元)
    main_net_ratio: Mapped[Decimal | None] = mapped_column(_RATIO, nullable=True)   # 主力净占比(%)
    super_large_net: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    large_net: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    medium_net: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    small_net: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinancialSummary(Base):
    """财务摘要的追加式 PIT 版本（按报告期和可用时点）。"""

    __tablename__ = "financial_summaries"
    __table_args__ = (
        UniqueConstraint(
            "code",
            "report_date",
            "vintage",
            name="uq_financial_summaries_code_report_vintage",
        ),
        Index(
            "ix_financial_summaries_code_report_available",
            "code",
            "report_date",
            "available_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    announced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    eps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)        # 每股收益
    bps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)        # 每股净资产
    roe: Mapped[Decimal | None] = mapped_column(_RATIO, nullable=True)                # 净资产收益率(%)
    revenue: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)           # 营业收入(元)
    net_profit: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)        # 净利润(元)
    gross_margin: Mapped[Decimal | None] = mapped_column(_RATIO, nullable=True)       # 毛利率(%)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DragonTiger(Base):
    """龙虎榜（个股按日上榜原因）。"""

    __tablename__ = "dragon_tiger"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    net_buy: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    buy_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    sell_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsItem(Base):
    """新闻 / 公告（可关联个股）。"""

    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # sha1(url|title)
    code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
