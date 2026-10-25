"""Bind backtest runs to immutable strategy versions.

Revision ID: 20260908_0015
Revises: 20260908_0014
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0015"
down_revision: str | Sequence[str] | None = "20260908_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("strategy_versions") as batch:
        batch.add_column(
            sa.Column(
                "implementation_version",
                sa.String(32),
                nullable=False,
                server_default=sa.text("'builtin-v1'"),
            )
        )
    op.execute(
        sa.text(
            "UPDATE strategy_versions SET implementation_version="
            "'sandbox-signal-v1' WHERE definition_type='custom_python'"
        )
    )
    with op.batch_alter_table("strategy_versions") as batch:
        batch.alter_column(
            "implementation_version",
            existing_type=sa.String(32),
            server_default=None,
        )
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("strategy_id", sa.String(36)))
        batch.add_column(sa.Column("strategy_version_id", sa.String(36)))
        batch.add_column(sa.Column("strategy_version", sa.Integer()))
        batch.add_column(sa.Column("definition_sha256", sa.String(64)))
        batch.create_foreign_key(
            "fk_backtest_runs_strategy_id",
            "strategies",
            ["strategy_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_backtest_runs_strategy_version_id",
            "strategy_versions",
            ["strategy_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_backtest_runs_user_strategy_created",
        "backtest_runs",
        ["user_id", "strategy_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_runs_user_strategy_created", table_name="backtest_runs"
    )
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_constraint(
            "fk_backtest_runs_strategy_version_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_backtest_runs_strategy_id", type_="foreignkey"
        )
        batch.drop_column("definition_sha256")
        batch.drop_column("strategy_version")
        batch.drop_column("strategy_version_id")
        batch.drop_column("strategy_id")
    with op.batch_alter_table("strategy_versions") as batch:
        batch.drop_column("implementation_version")
