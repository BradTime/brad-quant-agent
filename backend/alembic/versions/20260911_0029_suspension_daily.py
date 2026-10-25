"""Add independent daily suspension evidence.

Revision ID: 20260911_0029
Revises: 20260911_0028
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_0029"
down_revision: str | Sequence[str] | None = "20260911_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_suspension_daily",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("reason", sa.String(128)),
        sa.Column("announced_date", sa.Date()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["code"], ["instruments.code"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_instrument_suspension_daily_date",
        "instrument_suspension_daily",
        ["trade_date"],
    )


def downgrade() -> None:
    op.drop_table("instrument_suspension_daily")
