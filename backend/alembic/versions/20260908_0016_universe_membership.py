"""Add materialized PIT A-share universe membership.

Revision ID: 20260908_0016
Revises: 20260908_0015
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0016"
down_revision: str | Sequence[str] | None = "20260908_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "universe_membership_daily",
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reasons_json", PORTABLE_JSON, nullable=False),
        sa.Column("average_amount", sa.Numeric(24, 4)),
        sa.Column("listing_sessions", sa.Integer()),
        sa.Column("rules_version", sa.String(16), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["code"], ["instruments.code"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("code", "trade_date", "rules_version"),
    )
    op.create_index(
        "ix_universe_membership_date_eligible",
        "universe_membership_daily",
        ["trade_date", "eligible"],
    )


def downgrade() -> None:
    op.drop_table("universe_membership_daily")
