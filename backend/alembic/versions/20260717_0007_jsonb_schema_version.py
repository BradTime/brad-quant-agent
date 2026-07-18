"""Migrate Text JSON blobs to JSONB (Postgres) with schemaVersion envelopes.

Revision ID: 20260717_0007
Revises: 20260717_0006
Create Date: 2026-07-18
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260717_0007"
down_revision: str | Sequence[str] | None = "20260717_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, nullable)
_COLUMNS: list[tuple[str, str, bool]] = [
    ("backtest_runs", "config_json", True),
    ("backtest_runs", "metrics_json", True),
    ("backtest_runs", "equity_json", True),
    ("backtest_runs", "trades_json", True),
    ("backtest_runs", "data_quality_json", True),
    ("strategies", "params_json", False),
    ("morning_briefs", "data_pack_json", True),
    ("research_reports", "plan_json", True),
    ("research_reports", "steps_json", True),
]


def _wrap_legacy_rows(conn, table: str, column: str) -> None:
    """Wrap bare JSON values as {schemaVersion:1, payload:...} when missing envelope."""
    if conn is None:
        return
    result = conn.execute(sa.text(f"SELECT id, {column} AS raw FROM {table}"))
    if result is None:
        # offline --sql：无真实连接，跳过数据回填
        return
    rows = result.mappings()
    for row in rows:
        raw = row["raw"]
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                continue
        else:
            value = raw
        if isinstance(value, dict) and "schemaVersion" in value and "payload" in value:
            continue
        wrapped = json.dumps(
            {"schemaVersion": 1, "payload": value},
            ensure_ascii=False,
            default=str,
        )
        conn.execute(
            sa.text(f"UPDATE {table} SET {column} = CAST(:wrapped AS jsonb) WHERE id = :id"),
            {"wrapped": wrapped, "id": row["id"]},
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        # offline --sql / 非 PG：DDL 由后续 online 跑；SQLite 由 ORM PortableJSON 覆盖
        return

    for table, column, nullable in _COLUMNS:
        # Text → jsonb (invalid JSON becomes NULL for nullable cols)
        if nullable:
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                    ALTER COLUMN {column} TYPE jsonb
                    USING CASE
                        WHEN {column} IS NULL OR btrim({column}) = '' THEN NULL
                        WHEN {column}::text ~ '^\\s*[\\{{\\[]'
                            THEN {column}::jsonb
                        ELSE NULL
                    END
                    """
                )
            )
        else:
            op.execute(
                sa.text(
                    f"""
                    ALTER TABLE {table}
                    ALTER COLUMN {column} TYPE jsonb
                    USING CASE
                        WHEN {column} IS NULL OR btrim({column}) = '' THEN '{{}}'::jsonb
                        WHEN {column}::text ~ '^\\s*[\\{{\\[]'
                            THEN {column}::jsonb
                        ELSE '{{}}'::jsonb
                    END
                    """
                )
            )
            op.alter_column(
                table,
                column,
                existing_type=postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            )

    conn = op.get_bind()
    for table, column, _nullable in _COLUMNS:
        _wrap_legacy_rows(conn, table, column)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table, column, nullable in reversed(_COLUMNS):
        op.execute(
            sa.text(
                f"""
                ALTER TABLE {table}
                ALTER COLUMN {column} TYPE text
                USING {column}::text
                """
            )
        )
        if not nullable:
            op.alter_column(
                table,
                column,
                existing_type=sa.Text(),
                nullable=False,
                server_default="{}",
            )
