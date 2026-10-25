"""Add immutable fixed-pool historical moneyflow snapshots.

Revision ID: 20261025_0032
Revises: 20261025_0031
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261025_0032"
down_revision: str | Sequence[str] | None = "20261025_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "moneyflow_history_snapshots",
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
            name="uq_moneyflow_history_snapshot_scope",
        ),
    )
    op.create_table(
        "tushare_moneyflow_daily",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("net_amount", sa.Numeric(24, 4), nullable=False),
        sa.Column(
            "small_net_amount", sa.Numeric(24, 4), nullable=False
        ),
        sa.Column(
            "medium_net_amount", sa.Numeric(24, 4), nullable=False
        ),
        sa.Column(
            "large_net_amount", sa.Numeric(24, 4), nullable=False
        ),
        sa.Column(
            "extra_large_net_amount",
            sa.Numeric(24, 4),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["moneyflow_history_snapshots.id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["code"], ["instruments.code"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_tushare_moneyflow_snapshot_date",
        "tushare_moneyflow_daily",
        ["snapshot_id", "trade_date"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_moneyflow_history_snapshot()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'moneyflow history snapshots are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER moneyflow_history_snapshots_immutable
            BEFORE UPDATE OR DELETE ON moneyflow_history_snapshots
            FOR EACH ROW EXECUTE FUNCTION protect_moneyflow_history_snapshot()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_tushare_moneyflow_daily()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'manifested moneyflow history is immutable';
              END IF;
              IF EXISTS (
                SELECT 1 FROM moneyflow_history_snapshots
                WHERE id = NEW.snapshot_id
              ) THEN
                RAISE EXCEPTION 'manifested moneyflow history is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER tushare_moneyflow_daily_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON tushare_moneyflow_daily
            FOR EACH ROW EXECUTE FUNCTION protect_tushare_moneyflow_daily()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER tushare_moneyflow_daily_immutable "
            "ON tushare_moneyflow_daily"
        )
        op.execute("DROP FUNCTION protect_tushare_moneyflow_daily()")
        op.execute(
            "DROP TRIGGER moneyflow_history_snapshots_immutable "
            "ON moneyflow_history_snapshots"
        )
        op.execute("DROP FUNCTION protect_moneyflow_history_snapshot()")
    op.drop_index(
        "ix_tushare_moneyflow_snapshot_date",
        table_name="tushare_moneyflow_daily",
    )
    op.drop_table("tushare_moneyflow_daily")
    op.drop_table("moneyflow_history_snapshots")
