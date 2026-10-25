"""Guard full-A jobs and account deletion races.

Revision ID: 20260908_0017
Revises: 20260908_0016
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0017"
down_revision: str | Sequence[str] | None = "20260908_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not op.get_context().as_sql:
        duplicate = op.get_bind().execute(
            sa.text(
                "SELECT user_id FROM backtest_jobs "
                "WHERE kind='full_a' AND status IN ('queued','running') "
                "GROUP BY user_id HAVING count(*) > 1 LIMIT 1"
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise RuntimeError(
                "duplicate active full_a jobs must be resolved before migration"
            )
    op.execute(
        sa.text(
            "UPDATE backtest_runs SET user_id = NULL "
            "WHERE user_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM users WHERE users.id = backtest_runs.user_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM backtest_jobs WHERE NOT EXISTS "
            "(SELECT 1 FROM users WHERE users.id = backtest_jobs.user_id)"
        )
    )
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("job_id", sa.String(36)))
        batch.create_unique_constraint(
            "uq_backtest_runs_job_id", ["job_id"]
        )
        batch.create_foreign_key(
            "fk_backtest_runs_user_id",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("backtest_jobs") as batch:
        batch.add_column(sa.Column("claim_token", sa.String(36)))
        batch.create_foreign_key(
            "fk_backtest_jobs_user_id",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        "uq_backtest_jobs_active_full_a",
        "backtest_jobs",
        ["user_id", "kind"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'full_a' AND status IN ('queued','running')"
        ),
        sqlite_where=sa.text(
            "kind = 'full_a' AND status IN ('queued','running')"
        ),
    )
    op.create_index(
        "ix_daily_bars_trade_date",
        "daily_bars",
        ["trade_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_bars_trade_date", table_name="daily_bars")
    op.drop_index(
        "uq_backtest_jobs_active_full_a",
        table_name="backtest_jobs",
    )
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_constraint(
            "fk_backtest_runs_user_id", type_="foreignkey"
        )
        batch.drop_constraint(
            "uq_backtest_runs_job_id", type_="unique"
        )
        batch.drop_column("job_id")
    with op.batch_alter_table("backtest_jobs") as batch:
        batch.drop_constraint(
            "fk_backtest_jobs_user_id", type_="foreignkey"
        )
        batch.drop_column("claim_token")
