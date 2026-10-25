"""Version moneyflow snapshot scope by availability policy.

Revision ID: 20261025_0033
Revises: 20261025_0032
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261025_0033"
down_revision: str | Sequence[str] | None = "20261025_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("moneyflow_history_snapshots") as batch:
        batch.drop_constraint(
            "uq_moneyflow_history_snapshot_scope", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_moneyflow_history_snapshot_scope",
            [
                "as_of_date",
                "start_date",
                "end_date",
                "codes_sha256",
                "availability_policy",
            ],
        )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.exec_driver_sql(
        """
        SELECT 1
        FROM moneyflow_history_snapshots
        GROUP BY as_of_date, start_date, end_date, codes_sha256
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade moneyflow scope with multiple policies"
        )
    with op.batch_alter_table("moneyflow_history_snapshots") as batch:
        batch.drop_constraint(
            "uq_moneyflow_history_snapshot_scope", type_="unique"
        )
        batch.create_unique_constraint(
            "uq_moneyflow_history_snapshot_scope",
            ["as_of_date", "start_date", "end_date", "codes_sha256"],
        )
