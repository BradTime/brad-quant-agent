"""Create the current application schema or adopt a create_all database.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17 12:39:06.588152

"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic.migration import MigrationContext
from pgvector.sqlalchemy import Vector
from sqlalchemy import inspect

from alembic import context
from alembic import op as alembic_op

# revision identifiers, used by Alembic.
revision: str = "20260717_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TABLES: frozenset[str] = frozenset(
    {
        "adjust_factors",
        "backtest_runs",
        "capital_flows",
        "chat_messages",
        "chat_sessions",
        "daily_bars",
        "documents",
        "dragon_tiger",
        "financial_summaries",
        "instruments",
        "minute_bars",
        "morning_briefs",
        "news_items",
        "research_reports",
        "sim_accounts",
        "sim_orders",
        "sim_positions",
        "sim_trades",
        "strategies",
        "user_memories",
        "users",
        "watchlist_items",
    }
)
BASELINE_NEW_TABLES: frozenset[str] = frozenset({"ingestion_runs"})
_BASELINE_TABLES = LEGACY_TABLES | BASELINE_NEW_TABLES
_HNSW_INDEX = "ix_documents_embedding_hnsw"
_HNSW_SIGNATURE_SQL = sa.text(
    "SELECT am.amname, target.relname, attribute.attname, opclass.opcname, "
    "       index_metadata.indisvalid, index_metadata.indnkeyatts "
    "FROM pg_class AS index_relation "
    "JOIN pg_namespace AS namespace "
    "  ON namespace.oid = index_relation.relnamespace "
    "JOIN pg_index AS index_metadata "
    "  ON index_metadata.indexrelid = index_relation.oid "
    "JOIN pg_class AS target ON target.oid = index_metadata.indrelid "
    "JOIN pg_am AS am ON am.oid = index_relation.relam "
    "LEFT JOIN LATERAL unnest(index_metadata.indkey) WITH ORDINALITY "
    "  AS key_column(attnum, position) ON true "
    "LEFT JOIN pg_attribute AS attribute "
    "  ON attribute.attrelid = target.oid "
    " AND attribute.attnum = key_column.attnum "
    "LEFT JOIN LATERAL unnest(index_metadata.indclass) WITH ORDINALITY "
    "  AS operator_class(opclass_oid, position) "
    "  ON operator_class.position = key_column.position "
    "LEFT JOIN pg_opclass AS opclass "
    "  ON opclass.oid = operator_class.opclass_oid "
    "WHERE namespace.nspname = current_schema() "
    "  AND index_relation.relname = :name "
    "ORDER BY key_column.position"
)
_EXPECTED_HNSW_SIGNATURE = [
    ("hnsw", "documents", "embedding", "vector_cosine_ops", True, 1)
]


class _AdoptingOperations:
    """Skip objects already created by the legacy ``create_all`` workflow."""

    def __init__(self, existing_tables: set[str]) -> None:
        self.existing_tables = existing_tables

    @staticmethod
    def f(name: str) -> Any:
        return alembic_op.f(name)

    def create_table(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name in self.existing_tables:
            return None
        return alembic_op.create_table(name, *args, **kwargs)

    def create_index(
        self,
        name: str,
        table_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if table_name in self.existing_tables:
            return None
        return alembic_op.create_index(name, table_name, *args, **kwargs)


class _FrozenMetadataOperations:
    """Build immutable revision expectations from the creation operations below."""

    def __init__(self, metadata: sa.MetaData) -> None:
        self.metadata = metadata

    @staticmethod
    def f(name: str) -> str:
        return name

    def create_table(self, name: str, *args: Any, **kwargs: Any) -> sa.Table:
        return sa.Table(name, self.metadata, *args, **kwargs)

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: Sequence[str],
        *,
        unique: bool,
        **kwargs: Any,
    ) -> sa.Index:
        table = self.metadata.tables[table_name]
        return sa.Index(
            name,
            *(table.c[column_name] for column_name in columns),
            unique=unique,
            **kwargs,
        )


def _existing_tables() -> set[str]:
    if context.is_offline_mode():
        return set()
    return set(inspect(alembic_op.get_bind()).get_table_names())


def _foreign_key_signature(constraint: sa.ForeignKeyConstraint) -> tuple[Any, ...]:
    elements = list(constraint.elements)
    return (
        tuple(element.parent.name for element in elements),
        elements[0].column.table.schema,
        elements[0].column.table.name,
        tuple(element.column.name for element in elements),
        (constraint.ondelete or "").upper(),
        (constraint.onupdate or "").upper(),
    )


def _inspected_foreign_key_signature(foreign_key: dict[str, Any]) -> tuple[Any, ...]:
    options = foreign_key.get("options") or {}
    return (
        tuple(foreign_key.get("constrained_columns") or ()),
        foreign_key.get("referred_schema"),
        foreign_key.get("referred_table"),
        tuple(foreign_key.get("referred_columns") or ()),
        str(options.get("ondelete") or "").upper(),
        str(options.get("onupdate") or "").upper(),
    )


def _normalize_check_sqltext(sqltext: Any) -> str:
    """Normalize metadata SQL and PostgreSQL's IN-to-ANY rewrite."""
    normalized = re.sub(
        r"::\s*(?:character\s+varying|text)(?:\s*\[\s*\])?",
        "",
        str(sqltext),
        flags=re.IGNORECASE,
    )
    parts = re.split(r"('(?:''|[^'])*')", normalized)
    normalized = "".join(
        part if index % 2 else re.sub(r"\s+", "", part.replace('"', "").lower())
        for index, part in enumerate(parts)
    )
    any_array = re.fullmatch(
        r"(?P<column>[a-z_][a-z0-9_.]*)=any\(array\[(?P<values>.*)\]\)",
        normalized,
    )
    if any_array is not None:
        return f"{any_array['column']}in({any_array['values']})"
    return normalized


def _normalize_server_default(server_default: Any) -> str | None:
    """Normalize explicit defaults without changing quoted literal values."""
    if server_default is None:
        return None
    parts = re.split(r"('(?:''|[^'])*')", str(server_default).strip())
    normalized = "".join(
        part if index % 2 else re.sub(r"\s+", "", part.lower())
        for index, part in enumerate(parts)
    )
    if normalized in {
        "current_timestamp",
        "current_timestamp()",
        "now()",
        "transaction_timestamp()",
    }:
        return "current_timestamp"
    return normalized


def _validate_existing_schema() -> set[str]:
    """Verify a pre-Alembic database before adopting any managed table."""
    bind = alembic_op.get_bind()
    inspector = inspect(bind)
    actual_tables = set(inspector.get_table_names())
    expected_tables = _BASELINE_TABLES & actual_tables
    mismatches: list[str] = []

    for table_name in sorted(LEGACY_TABLES - actual_tables):
        mismatches.append(f"{table_name} table is missing")

    migration_context = MigrationContext.configure(
        bind,
        opts={"compare_type": True},
    )
    for table_name in sorted(expected_tables):
        expected_table = _FROZEN_BASELINE_METADATA.tables[table_name]
        reflected_table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
        inspected_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        expected_columns = set(expected_table.columns.keys())
        actual_columns = set(inspected_columns)

        for column_name in sorted(expected_columns - actual_columns):
            mismatches.append(f"{table_name}.{column_name} is missing")
        for column_name in sorted(actual_columns - expected_columns):
            mismatches.append(f"{table_name}.{column_name} is not present in metadata")

        for column_name in sorted(expected_columns & actual_columns):
            expected_column = expected_table.c[column_name]
            actual_column = reflected_table.c[column_name]
            if bool(inspected_columns[column_name]["nullable"]) != bool(
                expected_column.nullable
            ):
                mismatches.append(
                    f"{table_name}.{column_name} nullability differs from metadata"
                )
            if migration_context.impl.compare_type(actual_column, expected_column):
                actual_type = actual_column.type.compile(dialect=bind.dialect)
                expected_type = expected_column.type.compile(dialect=bind.dialect)
                mismatches.append(
                    f"{table_name}.{column_name} type is {actual_type}, "
                    f"expected {expected_type}"
                )
            if expected_column.server_default is not None:
                actual_default = _normalize_server_default(
                    inspected_columns[column_name].get("default")
                )
                expected_default = _normalize_server_default(
                    expected_column.server_default.arg
                )
                if actual_default != expected_default:
                    mismatches.append(
                        f"{table_name}.{column_name} server default is "
                        f"{actual_default!r}, expected {expected_default!r}"
                    )

        expected_primary_key = tuple(
            column.name for column in expected_table.primary_key.columns
        )
        actual_primary_key = tuple(
            inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
        )
        if actual_primary_key != expected_primary_key:
            mismatches.append(
                f"{table_name} primary key is {actual_primary_key}, "
                f"expected {expected_primary_key}"
            )

        actual_unique_columns = {
            tuple(constraint.get("column_names") or ())
            for constraint in inspector.get_unique_constraints(table_name)
        }
        expected_unique_constraints = {
            tuple(column.name for column in constraint.columns)
            for constraint in expected_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        for unique_columns in sorted(
            expected_unique_constraints - actual_unique_columns
        ):
            mismatches.append(
                f"{table_name} unique constraint on {unique_columns} is missing"
            )

        actual_foreign_keys = {
            _inspected_foreign_key_signature(foreign_key)
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        expected_foreign_keys = {
            _foreign_key_signature(constraint)
            for constraint in expected_table.constraints
            if isinstance(constraint, sa.ForeignKeyConstraint)
        }
        for foreign_key in sorted(
            expected_foreign_keys - actual_foreign_keys,
            key=repr,
        ):
            mismatches.append(f"{table_name} foreign key {foreign_key} is missing")

        actual_checks = {
            constraint["name"]: _normalize_check_sqltext(constraint["sqltext"])
            for constraint in inspector.get_check_constraints(table_name)
            if constraint.get("name")
        }
        expected_checks = {
            constraint.name: _normalize_check_sqltext(constraint.sqltext)
            for constraint in expected_table.constraints
            if isinstance(constraint, sa.CheckConstraint) and constraint.name
        }
        for constraint_name, expected_sqltext in sorted(expected_checks.items()):
            actual_sqltext = actual_checks.get(constraint_name)
            if actual_sqltext != expected_sqltext:
                mismatches.append(
                    f"{table_name} check constraint {constraint_name} is "
                    f"{actual_sqltext!r}, expected {expected_sqltext!r}"
                )

        actual_indexes = {
            index["name"]: (
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(table_name)
        }
        for index in sorted(expected_table.indexes, key=lambda item: item.name or ""):
            expected_index = (
                tuple(column.name for column in index.columns),
                bool(index.unique),
            )
            if actual_indexes.get(index.name) != expected_index:
                mismatches.append(
                    f"{table_name} index {index.name} is "
                    f"{actual_indexes.get(index.name)!r}, expected {expected_index!r}"
                )

    if mismatches:
        details = "\n- ".join(mismatches)
        raise RuntimeError(
            "Pre-Alembic schema does not match the frozen baseline contract; "
            f"baseline adoption aborted:\n- {details}"
        )
    return expected_tables


def _ensure_hnsw_index() -> None:
    bind = alembic_op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if context.is_offline_mode():
        alembic_op.execute(
            "CREATE INDEX ix_documents_embedding_hnsw "
            "ON documents USING hnsw (embedding vector_cosine_ops)"
        )
        return

    signature = [
        tuple(row)
        for row in bind.execute(
            _HNSW_SIGNATURE_SQL,
            {"name": _HNSW_INDEX},
        )
    ]
    if signature and signature != _EXPECTED_HNSW_SIGNATURE:
        raise RuntimeError(
            f"Existing index {_HNSW_INDEX!r} is not the required "
            "documents.embedding HNSW index with vector_cosine_ops; "
            f"found {signature!r}"
        )
    if not signature:
        alembic_op.execute(
            "CREATE INDEX ix_documents_embedding_hnsw "
            "ON documents USING hnsw (embedding vector_cosine_ops)"
        )


def _run_baseline_operations(op: Any) -> None:
    """Run the frozen 20260717 table and index definitions."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "adjust_factors",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("adjust_factor", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("fore_adjust_factor", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("back_adjust_factor", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "ex_date"),
    )
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("equity_json", sa.Text(), nullable=True),
        sa.Column("trades_json", sa.Text(), nullable=True),
        sa.Column("data_quality_json", sa.Text(), nullable=True),
        sa.Column("engine", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_backtest_runs_user_id"), "backtest_runs", ["user_id"], unique=False)
    op.create_table(
        "capital_flows",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("main_net", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("main_net_ratio", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("super_large_net", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("large_net", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("medium_net", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("small_net", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "trade_date"),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_index(
        "ix_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at"], unique=False
    )
    op.create_table(
        "daily_bars",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "trade_date"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("chunk", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(dim=512), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("meta", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_code"), "documents", ["code"], unique=False)
    op.create_index(op.f("ix_documents_published_at"), "documents", ["published_at"], unique=False)
    op.create_index(op.f("ix_documents_ref_id"), "documents", ["ref_id"], unique=False)
    op.create_index(op.f("ix_documents_source"), "documents", ["source"], unique=False)
    op.create_table(
        "dragon_tiger",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("net_buy", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("buy_amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("sell_amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "trade_date", "reason"),
    )
    op.create_table(
        "financial_summaries",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
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
        sa.PrimaryKeyConstraint("code", "report_date"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("datasets_json", sa.Text(), nullable=False),
        sa.Column("error_json", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'partial', 'failed')", name="ck_ingestion_runs_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_runs_code"), "ingestion_runs", ["code"], unique=False)
    op.create_index(
        "ix_ingestion_runs_covering",
        "ingestion_runs",
        ["code", "start_date", "end_date", "started_at"],
        unique=False,
    )
    op.create_table(
        "instruments",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("exchange", sa.String(length=4), nullable=False),
        sa.Column("security_type", sa.String(length=16), nullable=False),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column("is_suspended", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index(op.f("ix_instruments_exchange"), "instruments", ["exchange"], unique=False)
    op.create_index(
        op.f("ix_instruments_security_type"), "instruments", ["security_type"], unique=False
    )
    op.create_table(
        "minute_bars",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("dt", sa.DateTime(), nullable=False),
        sa.Column("period", sa.String(length=4), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code", "dt", "period"),
    )
    op.create_table(
        "morning_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data_pack_json", sa.Text(), nullable=True),
        sa.Column("source_note", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_morning_briefs_trade_date"), "morning_briefs", ["trade_date"], unique=False
    )
    op.create_index(op.f("ix_morning_briefs_user_id"), "morning_briefs", ["user_id"], unique=False)
    op.create_table(
        "news_items",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_news_items_code"), "news_items", ["code"], unique=False)
    op.create_index(
        op.f("ix_news_items_published_at"), "news_items", ["published_at"], unique=False
    )
    op.create_table(
        "research_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("question", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_research_reports_user_id"), "research_reports", ["user_id"], unique=False
    )
    op.create_table(
        "sim_accounts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("frozen_cash", sa.Float(), nullable=False),
        sa.Column("initial_cash", sa.Float(), nullable=False),
        sa.Column("last_settle_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "sim_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("order_type", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("filled_qty", sa.Integer(), nullable=False),
        sa.Column("avg_fill_price", sa.Float(), nullable=True),
        sa.Column("frozen", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sim_orders_user_id"), "sim_orders", ["user_id"], unique=False)
    op.create_table(
        "sim_positions",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("available_qty", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "code"),
    )
    op.create_table(
        "sim_trades",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("tax", sa.Float(), nullable=False),
        sa.Column(
            "traded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sim_trades_order_id"), "sim_trades", ["order_id"], unique=False)
    op.create_index(op.f("ix_sim_trades_user_id"), "sim_trades", ["user_id"], unique=False)
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("builtin_type", sa.String(length=32), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategies_user_id"), "strategies", ["user_id"], unique=False)
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_user_memories_user_key"),
    )
    op.create_index(op.f("ix_user_memories_user_id"), "user_memories", ["user_id"], unique=False)
    op.create_index(
        "ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("group_name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code", name="uq_watchlist_user_code"),
    )
    op.create_index(
        op.f("ix_watchlist_items_group_name"), "watchlist_items", ["group_name"], unique=False
    )
    op.create_index(
        op.f("ix_watchlist_items_user_id"), "watchlist_items", ["user_id"], unique=False
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_visible_role"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"], unique=False)
    op.create_index(
        "ix_chat_messages_user_session_created",
        "chat_messages",
        ["user_id", "session_id", "created_at"],
        unique=False,
    )
    # ### end Alembic commands ###


def _build_frozen_baseline_metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    _run_baseline_operations(_FrozenMetadataOperations(metadata))
    actual_tables = set(metadata.tables)
    if actual_tables != _BASELINE_TABLES:
        raise RuntimeError(
            "Frozen baseline operations do not match the table contract: "
            f"expected {sorted(_BASELINE_TABLES)}, got {sorted(actual_tables)}"
        )
    return metadata


_FROZEN_BASELINE_METADATA = _build_frozen_baseline_metadata()


def upgrade() -> None:
    """Create an empty schema or strictly adopt a matching legacy schema."""
    bind = alembic_op.get_bind()
    if context.is_offline_mode():
        alembic_op.execute(
            "-- OFFLINE BASELINE SQL IS FOR EMPTY DATABASES ONLY; "
            "it cannot validate or adopt an existing database"
        )
    if bind.dialect.name == "postgresql":
        alembic_op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    existing_tables = _existing_tables()
    pre_alembic_tables = existing_tables - {"alembic_version"}
    adopted_tables = _validate_existing_schema() if pre_alembic_tables else set()
    _run_baseline_operations(_AdoptingOperations(adopted_tables))
    _ensure_hnsw_index()


def downgrade() -> None:
    """Refuse destructive rollback of an adopted production baseline."""
    raise RuntimeError(
        "Baseline downgrade is disabled because it would drop every managed table. "
        "Restore from a backup or use a reviewed forward migration instead."
    )
