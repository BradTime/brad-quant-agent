"""Add immutable completeness manifests for PIT universes.

Revision ID: 20260908_0018
Revises: 20260908_0017
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0018"
down_revision: str | Sequence[str] | None = "20260908_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_snapshot_daily",
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rules_version", sa.String(16), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("filters_sha256", sa.String(64), nullable=False),
        sa.Column("membership_sha256", sa.String(64), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("trade_date", "rules_version"),
    )


def downgrade() -> None:
    op.drop_table("universe_snapshot_daily")
