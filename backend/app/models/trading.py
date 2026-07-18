"""模拟交易（Phase 3）ORM 模型。

play-money 模拟盘：账户/持仓/委托/成交。金额用 Float（模拟盘精度足够，避免 Decimal/float 混算）。
T+1 通过 ``SimPosition.available_qty``（当日买入冻结）+ 账户 ``last_settle_date`` 实现。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SimAccount(Base):
    __tablename__ = "sim_accounts"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cash: Mapped[float] = mapped_column(Float, default=0.0)          # 可用现金
    frozen_cash: Mapped[float] = mapped_column(Float, default=0.0)   # 挂买单冻结
    initial_cash: Mapped[float] = mapped_column(Float, default=0.0)
    last_settle_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimPosition(Base):
    __tablename__ = "sim_positions"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)             # 总持仓
    available_qty: Mapped[int] = mapped_column(Integer, default=0)   # 可卖（T+1 / 挂卖冻结后）
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)      # 含费用的摊薄成本
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SimOrder(Base):
    __tablename__ = "sim_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(32), default="")
    side: Mapped[str] = mapped_column(String(4))        # buy / sell
    order_type: Mapped[str] = mapped_column(String(8))  # limit / market
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # 限价单价格
    qty: Mapped[int] = mapped_column(Integer)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    frozen: Mapped[float] = mapped_column(Float, default=0.0)  # 挂买单冻结的现金
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending/filled/cancelled/rejected
    reason: Mapped[str] = mapped_column(String(255), default="")
    # A 股模拟盘默认 DAY：跨交易日在 settle / 日终任务中撤销，禁止隔夜成交
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    tif: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'DAY'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SimTrade(Base):
    __tablename__ = "sim_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(32), default="")
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float)   # price*qty
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
