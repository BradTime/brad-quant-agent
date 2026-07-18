"""Composite indexes + optional pg_trgm for RAG keyword path.

Revision ID: 20260717_0008
Revises: 20260717_0007
Create Date: 2026-07-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_0008"
down_revision: str | Sequence[str] | None = "20260717_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # 热路径复合索引（SQLite / Postgres 均支持）
    op.create_index(
        "ix_sim_orders_user_status_trade_date",
        "sim_orders",
        ["user_id", "status", "trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_sim_trades_user_traded_at",
        "sim_trades",
        ["user_id", "traded_at"],
        unique=False,
    )
    op.create_index(
        "ix_backtest_runs_user_created_at",
        "backtest_runs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_research_reports_user_created_at",
        "research_reports",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_morning_briefs_user_trade_date",
        "morning_briefs",
        ["user_id", "trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_news_items_code_published_at",
        "news_items",
        ["code", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_documents_source_ref_id",
        "documents",
        ["source", "ref_id"],
        unique=False,
    )
    op.create_index(
        "ix_watchlist_items_user_group",
        "watchlist_items",
        ["user_id", "group_name"],
        unique=False,
    )

    if bind.dialect.name != "postgresql":
        return

    # pg_trgm：加速 documents 标题/正文 ILIKE 关键词召回（H24）
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_documents_title_trgm "
            "ON documents USING gin (title gin_trgm_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_documents_chunk_trgm "
            "ON documents USING gin (chunk gin_trgm_ops)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP INDEX IF EXISTS ix_documents_chunk_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_documents_title_trgm"))

    for name, table in (
        ("ix_watchlist_items_user_group", "watchlist_items"),
        ("ix_documents_source_ref_id", "documents"),
        ("ix_news_items_code_published_at", "news_items"),
        ("ix_morning_briefs_user_trade_date", "morning_briefs"),
        ("ix_research_reports_user_created_at", "research_reports"),
        ("ix_backtest_runs_user_created_at", "backtest_runs"),
        ("ix_sim_trades_user_traded_at", "sim_trades"),
        ("ix_sim_orders_user_status_trade_date", "sim_orders"),
    ):
        op.drop_index(name, table_name=table)
