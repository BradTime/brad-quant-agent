"""Add DAY TIF trade_date on sim orders.

Revision ID: 20260717_0005
Revises: 20260717_0004
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_0005"
down_revision: str | Sequence[str] | None = "20260717_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sim_orders", sa.Column("trade_date", sa.Date(), nullable=True))
    op.add_column(
        "sim_orders",
        sa.Column("tif", sa.String(length=8), nullable=False, server_default="DAY"),
    )
    op.create_index("ix_sim_orders_trade_date", "sim_orders", ["trade_date"])
    # 历史挂单：用创建日（上海日历日近似）回填，便于下次 settle 按日撤销
    op.execute(
        sa.text(
            "UPDATE sim_orders "
            "SET trade_date = CAST(created_at AS date) "
            "WHERE trade_date IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_sim_orders_trade_date", table_name="sim_orders")
    op.drop_column("sim_orders", "tif")
    op.drop_column("sim_orders", "trade_date")
