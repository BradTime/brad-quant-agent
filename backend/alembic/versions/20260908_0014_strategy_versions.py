"""Add immutable strategy definitions and version history.

Revision ID: 20260908_0014
Revises: 20260902_0013
Create Date: 2026-09-08
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_0014"
down_revision: str | Sequence[str] | None = "20260902_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")
PROTOCOL_VERSION = "signal-v1"


def _payload(raw: object) -> object:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if (
        isinstance(raw, dict)
        and raw.get("schemaVersion") == 1
        and "payload" in raw
    ):
        return raw["payload"]
    return raw


def _definition_sha256(builtin_type: str, params: object) -> str:
    canonical = json.dumps(
        {
            "definitionType": "builtin",
            "builtinType": builtin_type,
            "params": _payload(params),
            "sourceCode": None,
            "protocolVersion": PROTOCOL_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("strategies") as batch:
        batch.add_column(
            sa.Column(
                "definition_type",
                sa.String(16),
                nullable=False,
                server_default=sa.text("'builtin'"),
            )
        )
        batch.add_column(
            sa.Column(
                "current_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch.add_column(
            sa.Column(
                "protocol_version",
                sa.String(16),
                nullable=False,
                server_default=sa.text(f"'{PROTOCOL_VERSION}'"),
            )
        )
        batch.add_column(sa.Column("definition_sha256", sa.String(64)))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "ck_strategies_definition_type",
            "definition_type IN ('builtin','custom_python')",
        )
        batch.create_check_constraint(
            "ck_strategies_current_version", "current_version >= 1"
        )

    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_type", sa.String(16), nullable=False),
        sa.Column("builtin_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("params_json", PORTABLE_JSON, nullable=False),
        sa.Column("source_code", sa.Text()),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.Column("protocol_version", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_strategy_versions_version"
        ),
        sa.CheckConstraint(
            "definition_type IN ('builtin','custom_python')",
            name="ck_strategy_versions_definition_type",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "strategy_id",
            "version",
            name="uq_strategy_versions_strategy_version",
        ),
    )
    op.create_index(
        "ix_strategy_versions_strategy_id",
        "strategy_versions",
        ["strategy_id"],
    )
    op.create_index(
        "ix_strategy_versions_user_id", "strategy_versions", ["user_id"]
    )

    if not op.get_context().as_sql:
        connection = op.get_bind()
        strategies = sa.table(
            "strategies",
            sa.column("id", sa.String),
            sa.column("user_id", sa.String),
            sa.column("builtin_type", sa.String),
            sa.column("category", sa.String),
            sa.column("params_json", PORTABLE_JSON),
            sa.column("definition_sha256", sa.String),
        )
        versions = sa.table(
            "strategy_versions",
            sa.column("id", sa.String),
            sa.column("strategy_id", sa.String),
            sa.column("user_id", sa.String),
            sa.column("version", sa.Integer),
            sa.column("definition_type", sa.String),
            sa.column("builtin_type", sa.String),
            sa.column("category", sa.String),
            sa.column("params_json", PORTABLE_JSON),
            sa.column("source_code", sa.Text),
            sa.column("definition_sha256", sa.String),
            sa.column("protocol_version", sa.String),
        )
        for row in connection.execute(
            sa.select(
                strategies.c.id,
                strategies.c.user_id,
                strategies.c.builtin_type,
                strategies.c.category,
                strategies.c.params_json,
            )
        ).mappings():
            digest = _definition_sha256(
                row["builtin_type"], row["params_json"]
            )
            connection.execute(
                sa.update(strategies)
                .where(strategies.c.id == row["id"])
                .values(definition_sha256=digest)
            )
            connection.execute(
                sa.insert(versions).values(
                    id=str(uuid4()),
                    strategy_id=row["id"],
                    user_id=row["user_id"],
                    version=1,
                    definition_type="builtin",
                    builtin_type=row["builtin_type"],
                    category=row["category"],
                    params_json=row["params_json"],
                    source_code=None,
                    definition_sha256=digest,
                    protocol_version=PROTOCOL_VERSION,
                )
            )
    with op.batch_alter_table("strategies") as batch:
        batch.alter_column(
            "definition_sha256",
            existing_type=sa.String(64),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_table("strategy_versions")
    with op.batch_alter_table("strategies") as batch:
        batch.drop_constraint(
            "ck_strategies_current_version", type_="check"
        )
        batch.drop_constraint("ck_strategies_definition_type", type_="check")
        batch.drop_column("definition_sha256")
        batch.drop_column("deleted_at")
        batch.drop_column("protocol_version")
        batch.drop_column("current_version")
        batch.drop_column("definition_type")
