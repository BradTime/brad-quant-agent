"""Add M3 prediction and portfolio audit tables.

Revision ID: 20260909_0020
Revises: 20260909_0019
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260909_0020"
down_revision: str | Sequence[str] | None = "20260909_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "prediction_model_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("feature_schema_version", sa.String(32), nullable=False),
        sa.Column("data_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_path", sa.String(1024)),
        sa.Column("artifact_sha256", sa.String(64)),
        sa.Column("metrics_json", PORTABLE_JSON, nullable=False),
        sa.Column("training_start", sa.Date(), nullable=False),
        sa.Column("training_end", sa.Date(), nullable=False),
        sa.Column(
            "is_champion",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        "ix_prediction_model_runs_user_id",
        "prediction_model_runs",
        ["user_id"],
    )
    op.create_table(
        "prediction_forecasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_run_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("probability_up", sa.Float(), nullable=False),
        sa.Column("return_p10", sa.Float(), nullable=False),
        sa.Column("return_p50", sa.Float(), nullable=False),
        sa.Column("return_p90", sa.Float(), nullable=False),
        sa.Column("feature_sha256", sa.String(64), nullable=False),
        sa.Column(
            "inferred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["prediction_model_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "model_run_id",
            "code",
            "signal_date",
            name="uq_prediction_forecast_model_code_date",
        ),
    )
    op.create_index(
        "ix_prediction_forecasts_code_date",
        "prediction_forecasts",
        ["code", "signal_date"],
    )


def downgrade() -> None:
    op.drop_table("prediction_forecasts")
    op.drop_table("prediction_model_runs")
