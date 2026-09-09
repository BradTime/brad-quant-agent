"""Add authoritative M3 allocation inputs and audit.

Revision ID: 20260910_0022
Revises: 20260909_0021
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0022"
down_revision: str | Sequence[str] | None = "20260909_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "instrument_industry_vintages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("industry", sa.String(64), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "code",
            "vintage",
            name="uq_instrument_industry_code_vintage",
        ),
    )
    op.create_index(
        "ix_instrument_industry_code_available",
        "instrument_industry_vintages",
        ["code", "available_at"],
    )
    op.create_table(
        "portfolio_risk_profiles",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("capital_limit", sa.Float(), nullable=False),
        sa.Column("leverage_limit", sa.Float(), nullable=False),
        sa.Column("high_water_mark", sa.Float(), nullable=False),
        sa.Column(
            "kill_switch_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "regime_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("regime", sa.String(16), nullable=False),
        sa.Column("rules_version", sa.String(32), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_regime_snapshots_user_id",
        "regime_snapshots",
        ["user_id"],
    )
    op.create_table(
        "portfolio_allocation_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("regime_snapshot_id", sa.String(36), nullable=False),
        sa.Column("model_run_id", sa.String(36), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("risk_state", sa.String(24), nullable=False),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["regime_snapshot_id"],
            ["regime_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["prediction_model_runs.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_portfolio_allocation_decisions_user_id",
        "portfolio_allocation_decisions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("portfolio_allocation_decisions")
    op.drop_table("regime_snapshots")
    op.drop_table("portfolio_risk_profiles")
    op.drop_table("instrument_industry_vintages")
