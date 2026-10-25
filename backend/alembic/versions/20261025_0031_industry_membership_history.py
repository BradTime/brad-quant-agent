"""Add immutable effective-dated industry membership snapshots.

Revision ID: 20261025_0031
Revises: 20260911_0030
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261025_0031"
down_revision: str | Sequence[str] | None = "20260911_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "industry_membership_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("taxonomy", sa.String(16), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("effective_floor", sa.Date(), nullable=False),
        sa.Column("source_row_count", sa.Integer(), nullable=False),
        sa.Column("persisted_row_count", sa.Integer(), nullable=False),
        sa.Column("unknown_code_count", sa.Integer(), nullable=False),
        sa.Column("classification_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "taxonomy",
            "level",
            "as_of_date",
            name="uq_industry_membership_snapshot_date",
        ),
    )
    op.create_table(
        "instrument_industry_membership_history",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("effective_from", sa.Date(), primary_key=True),
        sa.Column("effective_to", sa.Date()),
        sa.Column("industry_code", sa.String(16), nullable=False),
        sa.Column("industry_name", sa.String(64), nullable=False),
        sa.Column("source_in_date", sa.Date(), nullable=False),
        sa.Column("source_out_date", sa.Date()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_industry_membership_effective_range",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["industry_membership_snapshots.id"],
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["code"],
            ["instruments.code"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_industry_membership_snapshot_date",
        "instrument_industry_membership_history",
        ["snapshot_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_industry_membership_code_date",
        "instrument_industry_membership_history",
        ["code", "effective_from", "effective_to"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_industry_membership_snapshot()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'industry membership snapshots are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER industry_membership_snapshots_immutable
            BEFORE UPDATE OR DELETE ON industry_membership_snapshots
            FOR EACH ROW EXECUTE FUNCTION protect_industry_membership_snapshot()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_industry_membership_history()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'manifested industry membership is immutable';
              END IF;
              IF EXISTS (
                SELECT 1 FROM industry_membership_snapshots
                WHERE id = NEW.snapshot_id
              ) THEN
                RAISE EXCEPTION 'manifested industry membership is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER industry_membership_history_immutable
            BEFORE INSERT OR UPDATE OR DELETE
            ON instrument_industry_membership_history
            FOR EACH ROW EXECUTE FUNCTION protect_industry_membership_history()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER industry_membership_history_immutable "
            "ON instrument_industry_membership_history"
        )
        op.execute("DROP FUNCTION protect_industry_membership_history()")
        op.execute(
            "DROP TRIGGER industry_membership_snapshots_immutable "
            "ON industry_membership_snapshots"
        )
        op.execute("DROP FUNCTION protect_industry_membership_snapshot()")
    op.drop_index(
        "ix_industry_membership_code_date",
        table_name="instrument_industry_membership_history",
    )
    op.drop_index(
        "ix_industry_membership_snapshot_date",
        table_name="instrument_industry_membership_history",
    )
    op.drop_table("instrument_industry_membership_history")
    op.drop_table("industry_membership_snapshots")
