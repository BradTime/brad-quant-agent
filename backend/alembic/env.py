"""Alembic environment wired to the application's SQLAlchemy metadata."""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Connection, create_engine, pool, text

import app.models  # noqa: F401  (register every model on Base.metadata)
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_MANUAL_HNSW_INDEX = "ix_documents_embedding_hnsw"
# 迁移脚本单独创建、未挂在 ORM __table_args__ 上的索引（含 trgm / 复合索引）
_MIGRATION_MANAGED_INDEXES: frozenset[tuple[str, str]] = frozenset(
    {
        ("documents", "ix_documents_chunk_trgm"),
        ("documents", "ix_documents_title_trgm"),
        ("documents", "ix_documents_source_ref_id"),
        ("sim_orders", "ix_sim_orders_user_status_trade_date"),
        ("sim_trades", "ix_sim_trades_user_traded_at"),
        ("backtest_runs", "ix_backtest_runs_user_created_at"),
        ("backtest_jobs", "ix_backtest_jobs_status_created"),
        ("backtest_jobs", "ix_backtest_jobs_user_created"),
        ("research_reports", "ix_research_reports_user_created_at"),
        ("morning_briefs", "ix_morning_briefs_user_trade_date"),
        ("news_items", "ix_news_items_code_published_at"),
        ("watchlist_items", "ix_watchlist_items_user_group"),
    }
)
_MIGRATION_LOCK_SUFFIX = ":brad-quant-agent:alembic"
_valid_manual_indexes: set[tuple[str, str]] = set()

_HNSW_SIGNATURE_SQL = text(
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


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Exclude hand-managed HNSW and migration-only composite/trgm indexes."""
    table_name = getattr(getattr(object_, "table", None), "name", None)
    if type_ == "index" and reflected and name is not None and table_name is not None:
        key = (table_name, name)
        if key in _valid_manual_indexes or key in _MIGRATION_MANAGED_INDEXES:
            return False
    return True


def render_item(type_: str, object_: Any, autogen_context: Any) -> str | bool:
    """Render pgvector columns with a stable import in future revisions."""
    if type_ == "type" and isinstance(object_, Vector):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector(dim={object_.dim!r})"
    return False


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        render_item=render_item,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Render create-only SQL for an empty database without opening a connection."""
    _configure(
        url=settings.database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _acquire_postgresql_lock(connection: Connection) -> int:
    lock_key = connection.scalar(
        text("SELECT hashtextextended(current_database() || :suffix, 0)"),
        {"suffix": _MIGRATION_LOCK_SUFFIX},
    )
    if lock_key is None:
        raise RuntimeError("Unable to derive the PostgreSQL Alembic advisory lock key")
    connection.execute(
        text("SELECT pg_advisory_lock(:lock_key)"),
        {"lock_key": lock_key},
    )
    connection.commit()
    return int(lock_key)


def _release_postgresql_lock(connection: Connection, lock_key: int) -> None:
    if connection.in_transaction():
        connection.rollback()
    released = connection.scalar(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": lock_key},
    )
    connection.commit()
    if released is not True:
        raise RuntimeError("PostgreSQL Alembic advisory lock was not held by this session")


def _load_valid_manual_indexes(connection: Connection) -> set[tuple[str, str]]:
    if connection.dialect.name != "postgresql":
        return set()
    signature = [tuple(row) for row in connection.execute(
        _HNSW_SIGNATURE_SQL,
        {"name": _MANUAL_HNSW_INDEX},
    )]
    connection.commit()
    if signature == _EXPECTED_HNSW_SIGNATURE:
        return {("documents", _MANUAL_HNSW_INDEX)}
    return set()


def run_migrations_online() -> None:
    """Run migrations against the URL resolved by application settings."""
    global _valid_manual_indexes

    connectable = create_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        future=True,
    )
    try:
        with connectable.connect() as connection:
            lock_key: int | None = None
            try:
                if connection.dialect.name == "postgresql":
                    lock_key = _acquire_postgresql_lock(connection)
                _valid_manual_indexes = _load_valid_manual_indexes(connection)
                _configure(connection=connection)
                with context.begin_transaction():
                    context.run_migrations()
            finally:
                if lock_key is not None:
                    _release_postgresql_lock(connection, lock_key)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
