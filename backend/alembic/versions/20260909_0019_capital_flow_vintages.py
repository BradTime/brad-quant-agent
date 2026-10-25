"""Add append-only PIT capital-flow vintages.

Revision ID: 20260909_0019
Revises: 20260908_0018
Create Date: 2026-09-09
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_0019"
down_revision: str | Sequence[str] | None = "20260908_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIELDS = (
    "main_net",
    "main_net_ratio",
    "super_large_net",
    "large_net",
    "medium_net",
    "small_net",
)


def _vintage(row: dict) -> str:
    payload = {
        field: (
            format(Decimal(str(row[field])).normalize(), "f")
            if row.get(field) is not None
            else None
        )
        for field in _FIELDS
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def upgrade() -> None:
    op.create_table(
        "capital_flow_vintages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vintage", sa.String(64), nullable=False),
        sa.Column("main_net", sa.Numeric(24, 4)),
        sa.Column("main_net_ratio", sa.Numeric(12, 4)),
        sa.Column("super_large_net", sa.Numeric(24, 4)),
        sa.Column("large_net", sa.Numeric(24, 4)),
        sa.Column("medium_net", sa.Numeric(24, 4)),
        sa.Column("small_net", sa.Numeric(24, 4)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "code",
            "trade_date",
            "vintage",
            name="uq_capital_flow_vintages_code_date_vintage",
        ),
    )
    op.create_index(
        "ix_capital_flow_vintages_code_date_available",
        "capital_flow_vintages",
        ["code", "trade_date", "available_at"],
    )
    if not op.get_context().as_sql:
        connection = op.get_bind()
        legacy = sa.table(
            "capital_flows",
            sa.column("code"),
            sa.column("trade_date"),
            *(sa.column(field) for field in _FIELDS),
            sa.column("source"),
            sa.column("fetched_at"),
        )
        vintages = sa.table(
            "capital_flow_vintages",
            sa.column("id"),
            sa.column("code"),
            sa.column("trade_date"),
            sa.column("available_at"),
            sa.column("vintage"),
            *(sa.column(field) for field in _FIELDS),
            sa.column("source"),
            sa.column("fetched_at"),
            sa.column("last_seen_at"),
        )
        for row in connection.execute(sa.select(legacy)).mappings():
            values = dict(row)
            observed_at = values.get("fetched_at") or datetime.now(UTC)
            connection.execute(
                sa.insert(vintages).values(
                    id=str(uuid4()),
                    code=values["code"],
                    trade_date=values["trade_date"],
                    available_at=observed_at,
                    vintage=_vintage(values),
                    **{field: values.get(field) for field in _FIELDS},
                    source=values.get("source") or "legacy",
                    fetched_at=observed_at,
                    last_seen_at=observed_at,
                )
            )


def downgrade() -> None:
    op.drop_table("capital_flow_vintages")
