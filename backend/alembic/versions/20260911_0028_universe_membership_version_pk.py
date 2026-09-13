"""Include rules version in PIT universe membership primary key.

Revision ID: 20260911_0028
Revises: 20260911_0027
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_0028"
down_revision: str | Sequence[str] | None = "20260911_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    kwargs = (
        {"naming_convention": {"pk": "pk_%(table_name)s"}}
        if sqlite
        else {}
    )
    with op.batch_alter_table(
        "universe_membership_daily", **kwargs
    ) as batch:
        batch.drop_constraint(
            (
                "pk_universe_membership_daily"
                if sqlite
                else "universe_membership_daily_pkey"
            ),
            type_="primary",
        )
        batch.create_primary_key(
            "universe_membership_daily_pkey",
            ["code", "trade_date", "rules_version"],
        )


def downgrade() -> None:
    # Multiple rule versions may now exist for one code/date. Refuse a lossy
    # downgrade rather than silently deleting audit history.
    connection = op.get_bind()
    duplicate = connection.exec_driver_sql(
        """
        SELECT 1
        FROM universe_membership_daily
        GROUP BY code, trade_date
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade universe membership PK with multiple versions"
        )
    sqlite = op.get_bind().dialect.name == "sqlite"
    kwargs = (
        {"naming_convention": {"pk": "pk_%(table_name)s"}}
        if sqlite
        else {}
    )
    with op.batch_alter_table(
        "universe_membership_daily", **kwargs
    ) as batch:
        batch.drop_constraint(
            "universe_membership_daily_pkey",
            type_="primary",
        )
        batch.create_primary_key(
            "universe_membership_daily_pkey",
            ["code", "trade_date"],
        )
