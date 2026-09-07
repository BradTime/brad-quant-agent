"""Convert financial summaries to append-only point-in-time vintages.

Revision ID: 20260717_0002
Revises: 20260717_0001
Create Date: 2026-07-17

The upgrade rebuilds the table and copies every legacy row. Legacy rows were
first observed at ``fetched_at``, so both their PIT ``available_at`` and latest
``fetched_at`` retain that timestamp. Downgrade is deliberately disabled:
collapsing multiple vintages back to one row per report date would lose data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "20260717_0002"
down_revision: str | Sequence[str] | None = "20260717_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TABLE = "financial_summaries"
_NEW_TABLE = "financial_summaries_pit_new"
_METRICS = (
    "eps",
    "bps",
    "roe",
    "revenue",
    "net_profit",
    "gross_margin",
)


def _canonical_decimal(value: object) -> str | None:
    if value is None:
        return None
    decimal = Decimal(value)
    if decimal == 0:
        decimal = abs(decimal)
    return format(decimal.normalize(), "f")


def _vintage(row: sa.RowMapping) -> str:
    payload = {
        field: _canonical_decimal(row[field])
        for field in _METRICS
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _create_new_table() -> None:
    op.create_table(
        _NEW_TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vintage", sa.String(length=64), nullable=False),
        sa.Column("eps", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("bps", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("roe", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("revenue", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("net_profit", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("gross_margin", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "code",
            "report_date",
            "vintage",
            name="uq_financial_summaries_code_report_vintage",
        ),
    )


def _copy_legacy_rows() -> None:
    bind = op.get_bind()
    old = sa.table(
        _OLD_TABLE,
        sa.column("code", sa.String(length=16)),
        sa.column("report_date", sa.Date()),
        sa.column("eps", sa.Numeric(18, 4)),
        sa.column("bps", sa.Numeric(18, 4)),
        sa.column("roe", sa.Numeric(12, 4)),
        sa.column("revenue", sa.Numeric(24, 4)),
        sa.column("net_profit", sa.Numeric(24, 4)),
        sa.column("gross_margin", sa.Numeric(12, 4)),
        sa.column("source", sa.String(length=16)),
        sa.column("fetched_at", sa.DateTime(timezone=True)),
    )
    new = sa.table(
        _NEW_TABLE,
        sa.column("id", sa.String(length=36)),
        sa.column("code", sa.String(length=16)),
        sa.column("report_date", sa.Date()),
        sa.column("announced_at", sa.DateTime(timezone=True)),
        sa.column("available_at", sa.DateTime(timezone=True)),
        sa.column("vintage", sa.String(length=64)),
        sa.column("eps", sa.Numeric(18, 4)),
        sa.column("bps", sa.Numeric(18, 4)),
        sa.column("roe", sa.Numeric(12, 4)),
        sa.column("revenue", sa.Numeric(24, 4)),
        sa.column("net_profit", sa.Numeric(24, 4)),
        sa.column("gross_margin", sa.Numeric(12, 4)),
        sa.column("source", sa.String(length=16)),
        sa.column("fetched_at", sa.DateTime(timezone=True)),
    )
    for row in bind.execute(sa.select(old)).mappings():
        vintage = _vintage(row)
        identifier = str(
            uuid5(
                NAMESPACE_URL,
                f"financial-summary:{row['code']}:{row['report_date']}:{vintage}",
            )
        )
        bind.execute(
            new.insert().values(
                id=identifier,
                code=row["code"],
                report_date=row["report_date"],
                announced_at=None,
                available_at=row["fetched_at"],
                vintage=vintage,
                **{field: row[field] for field in _METRICS},
                source=row["source"],
                fetched_at=row["fetched_at"],
            )
        )


def upgrade() -> None:
    _create_new_table()
    if not context.is_offline_mode():
        _copy_legacy_rows()
    op.drop_table(_OLD_TABLE)
    op.rename_table(_NEW_TABLE, _OLD_TABLE)
    op.create_index(
        "ix_financial_summaries_code_report_available",
        _OLD_TABLE,
        ["code", "report_date", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Financial PIT downgrade is disabled because collapsing vintages would "
        "lose history; baseline downgrade is disabled. Restore a reviewed backup "
        "or apply a forward migration."
    )
