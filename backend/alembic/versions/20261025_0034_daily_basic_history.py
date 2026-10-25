"""Add immutable fixed-pool daily valuation snapshots.

Revision ID: 20261025_0034
Revises: 20261025_0033
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261025_0034"
down_revision: str | Sequence[str] | None = "20261025_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_basic_history_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("code_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("codes_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "availability_policy", sa.String(32), nullable=False
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "as_of_date",
            "start_date",
            "end_date",
            "codes_sha256",
            "availability_policy",
            name="uq_daily_basic_history_snapshot_scope",
        ),
    )
    op.create_table(
        "tushare_daily_basic",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("pe_ttm", sa.Numeric(24, 6)),
        sa.Column("pb", sa.Numeric(24, 6)),
        sa.Column("ps_ttm", sa.Numeric(24, 6)),
        sa.Column("dv_ttm", sa.Numeric(24, 6)),
        sa.Column("total_mv", sa.Numeric(24, 4), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["daily_basic_history_snapshots.id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["code"], ["instruments.code"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_tushare_daily_basic_snapshot_date",
        "tushare_daily_basic",
        ["snapshot_id", "trade_date"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_daily_basic_history_snapshot()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'daily basic history snapshots are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER daily_basic_history_snapshots_immutable
            BEFORE UPDATE OR DELETE ON daily_basic_history_snapshots
            FOR EACH ROW EXECUTE FUNCTION protect_daily_basic_history_snapshot()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_tushare_daily_basic()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'manifested daily basic history is immutable';
              END IF;
              IF EXISTS (
                SELECT 1 FROM daily_basic_history_snapshots
                WHERE id = NEW.snapshot_id
              ) THEN
                RAISE EXCEPTION 'manifested daily basic history is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER tushare_daily_basic_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON tushare_daily_basic
            FOR EACH ROW EXECUTE FUNCTION protect_tushare_daily_basic()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER tushare_daily_basic_immutable "
            "ON tushare_daily_basic"
        )
        op.execute("DROP FUNCTION protect_tushare_daily_basic()")
        op.execute(
            "DROP TRIGGER daily_basic_history_snapshots_immutable "
            "ON daily_basic_history_snapshots"
        )
        op.execute("DROP FUNCTION protect_daily_basic_history_snapshot()")
    op.drop_index(
        "ix_tushare_daily_basic_snapshot_date",
        table_name="tushare_daily_basic",
    )
    op.drop_table("tushare_daily_basic")
    op.drop_table("daily_basic_history_snapshots")
