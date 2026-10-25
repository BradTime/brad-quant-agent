"""Add immutable per-session Tushare bootstrap manifests.

Revision ID: 20260911_0030
Revises: 20260911_0029
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_0030"
down_revision: str | Sequence[str] | None = "20260911_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tushare_bootstrap_daily_manifests",
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("daily_count", sa.Integer(), nullable=False),
        sa.Column("factor_count", sa.Integer(), nullable=False),
        sa.Column("daily_sha256", sa.String(64), nullable=False),
        sa.Column("factor_sha256", sa.String(64), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_tushare_bootstrap_manifest_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'Tushare bootstrap manifests are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_manifested_daily_bar()
            RETURNS trigger AS $$
            DECLARE
              target_date date;
              target_code varchar;
            BEGIN
              IF TG_OP = 'DELETE' THEN
                target_date := OLD.trade_date;
                target_code := OLD.code;
              ELSE
                target_date := NEW.trade_date;
                target_code := NEW.code;
              END IF;
              IF TG_OP = 'UPDATE' AND (
                (OLD.code <> '000300.SH' AND EXISTS (
                  SELECT 1 FROM tushare_bootstrap_daily_manifests
                  WHERE trade_date = OLD.trade_date
                ))
                OR
                (NEW.code <> '000300.SH' AND EXISTS (
                  SELECT 1 FROM tushare_bootstrap_daily_manifests
                  WHERE trade_date = NEW.trade_date
                ))
              ) THEN
                RAISE EXCEPTION 'manifested daily bars are immutable';
              END IF;
              IF target_code <> '000300.SH' AND EXISTS (
                SELECT 1 FROM tushare_bootstrap_daily_manifests
                WHERE trade_date = target_date
              ) THEN
                RAISE EXCEPTION 'manifested daily bars are immutable';
              END IF;
              IF TG_OP = 'DELETE' THEN
                RETURN OLD;
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER manifested_daily_bars_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON daily_bars
            FOR EACH ROW EXECUTE FUNCTION protect_manifested_daily_bar()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_manifested_adjust_factor()
            RETURNS trigger AS $$
            DECLARE
              target_date date;
              target_code varchar;
            BEGIN
              IF TG_OP = 'DELETE' THEN
                target_date := OLD.ex_date;
                target_code := OLD.code;
              ELSE
                target_date := NEW.ex_date;
                target_code := NEW.code;
              END IF;
              IF TG_OP = 'UPDATE' AND (
                (OLD.code <> '000300.SH' AND EXISTS (
                  SELECT 1 FROM tushare_bootstrap_daily_manifests
                  WHERE trade_date = OLD.ex_date
                ))
                OR
                (NEW.code <> '000300.SH' AND EXISTS (
                  SELECT 1 FROM tushare_bootstrap_daily_manifests
                  WHERE trade_date = NEW.ex_date
                ))
              ) THEN
                RAISE EXCEPTION 'manifested adjustment factors are immutable';
              END IF;
              IF target_code <> '000300.SH' AND EXISTS (
                SELECT 1 FROM tushare_bootstrap_daily_manifests
                WHERE trade_date = target_date
              ) THEN
                RAISE EXCEPTION 'manifested adjustment factors are immutable';
              END IF;
              IF TG_OP = 'DELETE' THEN
                RETURN OLD;
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER manifested_adjust_factors_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON adjust_factors
            FOR EACH ROW EXECUTE FUNCTION protect_manifested_adjust_factor()
            """
        )
        op.execute(
            """
            CREATE TRIGGER tushare_bootstrap_manifests_append_only
            BEFORE UPDATE OR DELETE ON tushare_bootstrap_daily_manifests
            FOR EACH ROW EXECUTE FUNCTION reject_tushare_bootstrap_manifest_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER manifested_adjust_factors_immutable "
            "ON adjust_factors"
        )
        op.execute("DROP FUNCTION protect_manifested_adjust_factor()")
        op.execute(
            "DROP TRIGGER manifested_daily_bars_immutable ON daily_bars"
        )
        op.execute("DROP FUNCTION protect_manifested_daily_bar()")
        op.execute(
            "DROP TRIGGER tushare_bootstrap_manifests_append_only "
            "ON tushare_bootstrap_daily_manifests"
        )
        op.execute(
            "DROP FUNCTION reject_tushare_bootstrap_manifest_mutation()"
        )
    op.drop_table("tushare_bootstrap_daily_manifests")
