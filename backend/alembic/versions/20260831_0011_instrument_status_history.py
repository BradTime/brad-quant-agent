"""Add effective-dated instrument status history for PIT backtests.

Revision ID: 20260831_0011
Revises: 20260717_0010
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260831_0011"
down_revision: str | Sequence[str] | None = "20260717_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_status_history",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("status_type", sa.String(length=16), nullable=False),
        sa.Column("change_reason", sa.String(length=128), nullable=True),
        sa.Column("announced_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "start_date"),
    )
    op.create_index(
        "ix_instrument_status_history_lookup",
        "instrument_status_history",
        ["code", "start_date", "end_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_instrument_status_history_status_type"),
        "instrument_status_history",
        ["status_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_instrument_status_history_status_type"),
        table_name="instrument_status_history",
    )
    op.drop_index(
        "ix_instrument_status_history_lookup",
        table_name="instrument_status_history",
    )
    op.drop_table("instrument_status_history")
