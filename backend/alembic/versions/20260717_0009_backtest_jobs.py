"""Backtest async jobs (grid queue + cancel).

Revision ID: 20260717_0009
Revises: 20260717_0008
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_0009"
down_revision: str | Sequence[str] | None = "20260717_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="grid"),
        # queued | running | completed | failed | cancelled
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_backtest_jobs_status_created",
        "backtest_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_jobs_user_created",
        "backtest_jobs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_jobs_user_created", table_name="backtest_jobs")
    op.drop_index("ix_backtest_jobs_status_created", table_name="backtest_jobs")
    op.drop_table("backtest_jobs")
