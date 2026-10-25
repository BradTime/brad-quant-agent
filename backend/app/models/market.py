"""Market data ORM models.

Canonical instrument code = ``<6 digits>.<EXCH>`` e.g. ``600000.SH`` / ``000001.SZ``.
Daily/minute bars are stored **unadjusted**; adjustment is derived from
``AdjustFactor`` so we keep point-in-time correctness for backtests.

PIT (point-in-time) audit columns ``source`` + ``fetched_at`` record where and
when each row was pulled — required to avoid look-ahead / survivorship bias later.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_PRICE = Numeric(18, 4)
_AMOUNT = Numeric(24, 4)
_FACTOR = Numeric(18, 6)


class Instrument(Base):
    __tablename__ = "instruments"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    exchange: Mapped[str] = mapped_column(String(4), index=True)
    security_type: Mapped[str] = mapped_column(String(16), default="stock", index=True)
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delist_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="listed")
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InstrumentStatusHistory(Base):
    """Effective-dated security name/risk-warning status for PIT backtests."""

    __tablename__ = "instrument_status_history"
    __table_args__ = (
        Index(
            "ix_instrument_status_history_lookup",
            "code",
            "start_date",
            "end_date",
        ),
    )

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, primary_key=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    # normal / st / star_st / suspended / delisting / delisted. Boards such as
    # ChiNext still apply their board limit; trading_rules consumes ST states.
    status_type: Mapped[str] = mapped_column(String(16), default="normal", index=True)
    change_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    announced_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InstrumentIndustryVintage(Base):
    """First-observed, append-only industry classification."""

    __tablename__ = "instrument_industry_vintages"
    __table_args__ = (
        UniqueConstraint(
            "code",
            "vintage",
            name="uq_instrument_industry_code_vintage",
        ),
        Index(
            "ix_instrument_industry_code_available",
            "code",
            "available_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    vintage: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class InstrumentSuspensionDaily(Base):
    __tablename__ = "instrument_suspension_daily"
    __table_args__ = (
        Index(
            "ix_instrument_suspension_daily_date",
            "trade_date",
        ),
    )

    code: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("instruments.code", ondelete="RESTRICT"),
        primary_key=True,
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str | None] = mapped_column(String(128))
    announced_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailyBar(Base):
    __tablename__ = "daily_bars"
    __table_args__ = (
        Index("ix_daily_bars_trade_date", "trade_date"),
    )

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    close: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MinuteBar(Base):
    __tablename__ = "minute_bars"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    dt: Mapped[datetime] = mapped_column(DateTime(timezone=False), primary_key=True)
    period: Mapped[str] = mapped_column(String(4), primary_key=True)  # 1/5/15/30/60
    open: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    high: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    low: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    close: Mapped[Decimal | None] = mapped_column(_PRICE, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdjustFactor(Base):
    __tablename__ = "adjust_factors"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    adjust_factor: Mapped[Decimal | None] = mapped_column(_FACTOR, nullable=True)
    fore_adjust_factor: Mapped[Decimal | None] = mapped_column(_FACTOR, nullable=True)
    back_adjust_factor: Mapped[Decimal | None] = mapped_column(_FACTOR, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
