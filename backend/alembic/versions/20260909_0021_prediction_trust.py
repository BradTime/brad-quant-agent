"""Add trusted promotion and regime-breadth evidence.

Revision ID: 20260909_0021
Revises: 20260909_0020
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_0021"
down_revision: str | Sequence[str] | None = "20260909_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("universe_snapshot_daily") as batch:
        batch.add_column(sa.Column("advancing_count", sa.Integer()))
        batch.add_column(sa.Column("declining_count", sa.Integer()))
    if not op.get_context().as_sql:
        duplicate = op.get_bind().execute(
            sa.text(
                "SELECT count(*) FROM prediction_model_runs "
                "WHERE is_champion = true"
            )
        ).scalar_one()
        if duplicate > 1:
            raise RuntimeError(
                "multiple champion models must be resolved before migration"
            )
    op.create_index(
        "uq_prediction_model_single_champion",
        "prediction_model_runs",
        ["is_champion"],
        unique=True,
        postgresql_where=sa.text("is_champion = true"),
        sqlite_where=sa.text("is_champion = 1"),
    )
    op.create_table(
        "prediction_promotion_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_run_id", sa.String(36), nullable=False),
        sa.Column("previous_model_run_id", sa.String(36)),
        sa.Column("promoted_by_user_id", sa.String(36)),
        sa.Column(
            "promoted_by_user_id_snapshot",
            sa.String(36),
            nullable=False,
        ),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["prediction_model_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_model_run_id"],
            ["prediction_model_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["promoted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("prediction_promotion_audits")
    op.drop_index(
        "uq_prediction_model_single_champion",
        table_name="prediction_model_runs",
    )
    with op.batch_alter_table("universe_snapshot_daily") as batch:
        batch.drop_column("declining_count")
        batch.drop_column("advancing_count")
