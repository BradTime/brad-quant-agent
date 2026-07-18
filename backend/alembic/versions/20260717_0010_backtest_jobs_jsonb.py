"""Align backtest_jobs JSON columns with PortableJSON (JSONB on Postgres).

Revision ID: 20260717_0010
Revises: 20260717_0009
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260717_0010"
down_revision: str | Sequence[str] | None = "20260717_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for column in ("request_json", "result_json"):
        op.alter_column(
            "backtest_jobs",
            column,
            existing_type=sa.JSON(),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using=f"{column}::jsonb",
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for column in ("request_json", "result_json"):
        op.alter_column(
            "backtest_jobs",
            column,
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=sa.JSON(),
            postgresql_using=f"{column}::json",
            existing_nullable=True,
        )
