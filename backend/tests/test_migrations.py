from __future__ import annotations

import importlib.util
import logging.config
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (register every model on Base.metadata)
from app.core.config import settings
from app.db.base import Base
from app.models.market import Instrument
from app.models.user import User
from app.providers.base import FinancialSummaryDTO
from app.services import ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
ALEMBIC_DIR = BACKEND_ROOT / "alembic"
BASELINE_REVISION = "20260717_0001"
FINANCIAL_PIT_REVISION = "20260717_0002"
AUTH_THROTTLE_REVISION = "20260717_0003"
EMAIL_VERIFICATION_REVISION = "20260717_0004"
BACKTEST_JOBS_REVISION = "20260717_0010"
HEAD_REVISION = BACKTEST_JOBS_REVISION
HNSW_INDEX = "ix_documents_embedding_hnsw"
LEGACY_TABLES = frozenset(
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
NEW_BASELINE_TABLES = frozenset({"ingestion_runs"})
POST_BASELINE_TABLES = frozenset(
    {
        "auth_throttles",
        "email_verifications",
        "verification_email_outbox",
        "backtest_jobs",
    }
)

# ORM 相对 baseline 冻结契约多出的列：造「升级前库」时需剥掉，否则 baseline adoption 会拒收
_POST_BASELINE_COLUMNS: dict[str, frozenset[str]] = {
    "users": frozenset({"token_version", "email_verified_at"}),
    "sim_orders": frozenset({"tif", "trade_date"}),
}

# baseline 冻结为 TEXT；当前 ORM 为 JSONB，造预迁移库时降回 TEXT
_BASELINE_TEXT_JSON_COLUMNS: dict[str, frozenset[str]] = {
    "strategies": frozenset({"params_json"}),
    "backtest_runs": frozenset(
        {
            "config_json",
            "metrics_json",
            "equity_json",
            "trades_json",
            "data_quality_json",
        }
    ),
    "morning_briefs": frozenset({"data_pack_json"}),
    "research_reports": frozenset({"plan_json", "steps_json"}),
}


def _alembic_environment(database_url: URL) -> dict[str, str]:
    return {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": database_url.render_as_string(hide_password=False),
        "JWT_SECRET": "migration-test-secret-not-for-production",
    }


def _alembic_command(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments]


def _run_alembic(
    database_url: URL, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        _alembic_command(*arguments),
        cwd=BACKEND_ROOT,
        env=_alembic_environment(database_url),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope="module")
def postgres_admin_url() -> Iterator[URL]:
    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() != "postgresql":
        pytest.skip("DATABASE_URL 未配置为 PostgreSQL")

    admin_url = database_url.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL 不可用：{exc}")

    engine.dispose()
    yield admin_url


@pytest.fixture
def temporary_database(postgres_admin_url: URL) -> Iterator[Callable[[], URL]]:
    created: list[tuple[str, URL]] = []
    admin_engine = create_engine(
        postgres_admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )

    def create() -> URL:
        name = f"alembic_test_{uuid4().hex}"
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        database_url = make_url(settings.database_url).set(database=name)
        created.append((name, database_url))
        return database_url

    yield create

    for name, _ in reversed(created):
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin_engine.dispose()


def _table_counts(
    database_url: URL,
    table_names: Iterable[str] | None = None,
) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        names = table_names if table_names is not None else Base.metadata.tables
        with engine.connect() as connection:
            return {
                table_name: int(
                    connection.scalar(text(f'SELECT count(*) FROM "{table_name}"')) or 0
                )
                for table_name in sorted(names)
            }
    finally:
        engine.dispose()


def _create_pre_alembic_schema(
    database_url: URL,
    *,
    include_new_tables: bool = False,
) -> None:
    table_names = LEGACY_TABLES | (NEW_BASELINE_TABLES if include_new_tables else set())
    schema_metadata = MetaData()
    for table_name in sorted(table_names):
        if table_name == "financial_summaries":
            continue
        Base.metadata.tables[table_name].to_metadata(schema_metadata)
    Table(
        "financial_summaries",
        schema_metadata,
        Column("code", String(16), primary_key=True),
        Column("report_date", Date, primary_key=True),
        Column("eps", Numeric(18, 4), nullable=True),
        Column("bps", Numeric(18, 4), nullable=True),
        Column("roe", Numeric(12, 4), nullable=True),
        Column("revenue", Numeric(24, 4), nullable=True),
        Column("net_profit", Numeric(24, 4), nullable=True),
        Column("gross_margin", Numeric(12, 4), nullable=True),
        Column("source", String(16), nullable=False),
        Column(
            "fetched_at",
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        schema_metadata.create_all(bind=engine)
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                for table_name, columns in _POST_BASELINE_COLUMNS.items():
                    for column in columns:
                        connection.execute(
                            text(
                                f'ALTER TABLE "{table_name}" '
                                f'DROP COLUMN IF EXISTS "{column}"'
                            )
                        )
                for table_name, columns in _BASELINE_TEXT_JSON_COLUMNS.items():
                    for column in columns:
                        connection.execute(
                            text(
                                f'ALTER TABLE "{table_name}" '
                                f'ALTER COLUMN "{column}" TYPE TEXT '
                                f'USING "{column}"::text'
                            )
                        )
    finally:
        engine.dispose()


def _revision_rows(database_url: URL) -> list[str]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            return []
        with engine.connect() as connection:
            return list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _assert_baseline_objects(database_url: URL) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables)
        assert expected_tables <= actual_tables
        assert {
            "users",
            "instruments",
            "documents",
            "chat_sessions",
            "chat_messages",
            "strategies",
            "ingestion_runs",
            "auth_throttles",
            "email_verifications",
            "verification_email_outbox",
            "alembic_version",
        } <= actual_tables

        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == HEAD_REVISION
            )
            assert connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
            hnsw_definition = connection.execute(
                text(
                    "SELECT am.amname, target.relname, attribute.attname, opclass.opcname "
                    "FROM pg_class AS index_relation "
                    "JOIN pg_namespace AS namespace "
                    "  ON namespace.oid = index_relation.relnamespace "
                    "JOIN pg_index AS index_metadata "
                    "  ON index_metadata.indexrelid = index_relation.oid "
                    "JOIN pg_class AS target "
                    "  ON target.oid = index_metadata.indrelid "
                    "JOIN pg_am AS am ON am.oid = index_relation.relam "
                    "JOIN LATERAL unnest(index_metadata.indkey) WITH ORDINALITY "
                    "  AS key_column(attnum, position) ON true "
                    "JOIN pg_attribute AS attribute "
                    "  ON attribute.attrelid = target.oid "
                    " AND attribute.attnum = key_column.attnum "
                    "JOIN LATERAL unnest(index_metadata.indclass) WITH ORDINALITY "
                    "  AS operator_class(opclass_oid, position) "
                    "  ON operator_class.position = key_column.position "
                    "JOIN pg_opclass AS opclass "
                    "  ON opclass.oid = operator_class.opclass_oid "
                    "WHERE namespace.nspname = current_schema() "
                    "  AND index_relation.relname = :name "
                    "ORDER BY key_column.position"
                ),
                {"name": HNSW_INDEX},
            ).all()
            assert hnsw_definition == [
                ("hnsw", "documents", "embedding", "vector_cosine_ops")
            ]
    finally:
        engine.dispose()


def test_standard_alembic_layout_is_present() -> None:
    assert ALEMBIC_CONFIG.is_file()
    assert (ALEMBIC_DIR / "env.py").is_file()
    assert (ALEMBIC_DIR / "script.py.mako").is_file()
    assert (ALEMBIC_DIR / "versions" / f"{BASELINE_REVISION}_baseline.py").is_file()
    assert (
        ALEMBIC_DIR
        / "versions"
        / f"{FINANCIAL_PIT_REVISION}_financial_summary_pit.py"
    ).is_file()
    assert (
        ALEMBIC_DIR / "versions" / f"{AUTH_THROTTLE_REVISION}_auth_throttles.py"
    ).is_file()
    assert (
        ALEMBIC_DIR
        / "versions"
        / f"{EMAIL_VERIFICATION_REVISION}_email_verification.py"
    ).is_file()


def test_legacy_table_contract_matches_pre_branch_metadata() -> None:
    assert set(Base.metadata.tables) == LEGACY_TABLES | NEW_BASELINE_TABLES | POST_BASELINE_TABLES


def test_cli_migrate_upgrades_to_head(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from alembic import command
    from app.cli import main

    captured: dict[str, object] = {}

    def fake_upgrade(config: object, revision: str) -> None:
        captured["config"] = config
        captured["revision"] = revision

    monkeypatch.setattr(command, "upgrade", fake_upgrade)

    assert main(["migrate"]) == 0
    assert captured["revision"] == "head"
    assert Path(captured["config"].config_file_name) == ALEMBIC_CONFIG  # type: ignore[union-attr]
    assert "Alembic" in capsys.readouterr().out


def test_empty_postgres_upgrade_is_complete_repeatable_and_drift_free(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()

    _run_alembic(database_url, "upgrade", "head")
    _assert_baseline_objects(database_url)

    _run_alembic(database_url, "upgrade", "head")
    _assert_baseline_objects(database_url)

    _run_alembic(database_url, "check")


def test_offline_baseline_sql_states_it_is_only_for_empty_databases() -> None:
    database_url = make_url(settings.database_url)

    result = _run_alembic(database_url, "upgrade", "head", "--sql")

    assert "empty databases only" in result.stdout.lower()


def test_sqlite_upgrade_remains_compatible_without_postgresql_lock(tmp_path: Path) -> None:
    database_url = URL.create(
        "sqlite+pysqlite",
        database=str(tmp_path / "alembic.sqlite3"),
    )

    _run_alembic(database_url, "upgrade", "head")

    assert _revision_rows(database_url) == [HEAD_REVISION]


def test_email_verification_migration_marks_legacy_users_verified(tmp_path: Path) -> None:
    database_url = URL.create(
        "sqlite+pysqlite",
        database=str(tmp_path / "email-verification.sqlite3"),
    )
    _run_alembic(database_url, "upgrade", AUTH_THROTTLE_REVISION)
    engine = create_engine(database_url)
    created_at = "2026-07-01 02:03:04"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email, name, password_hash, role, created_at, updated_at) "
                    "VALUES ('legacy-verified', 'legacy@example.com', 'Legacy', "
                    "'hash', 'user', :created_at, :created_at)"
                ),
                {"created_at": created_at},
            )
    finally:
        engine.dispose()

    _run_alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT created_at, email_verified_at FROM users "
                    "WHERE id = 'legacy-verified'"
                )
            ).one()
            assert row.email_verified_at == row.created_at
    finally:
        engine.dispose()


def test_legacy_head_database_is_adopted_and_new_table_is_created(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                User.__table__.insert().values(
                    id="migration-user",
                    email="migration@example.com",
                    name="Migration",
                    password_hash="not-a-real-hash",
                    role="user",
                )
            )
            connection.execute(
                Instrument.__table__.insert().values(
                    code="600000.SH",
                    name="浦发银行",
                    exchange="SH",
                    security_type="stock",
                    is_suspended=False,
                    status="listed",
                    source="migration-test",
                )
            )
    finally:
        engine.dispose()

    counts_before = _table_counts(database_url, LEGACY_TABLES)
    _run_alembic(database_url, "upgrade", "head")
    counts_after = _table_counts(database_url, LEGACY_TABLES)

    assert counts_after == counts_before
    assert counts_after["users"] == 1
    assert counts_after["instruments"] == 1
    assert _table_counts(database_url, NEW_BASELINE_TABLES) == {"ingestion_runs": 0}
    _assert_baseline_objects(database_url)

    _run_alembic(database_url, "upgrade", "head")
    assert _table_counts(database_url, LEGACY_TABLES) == counts_before


def test_pre_alembic_schema_with_missing_legacy_table_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE strategies"))
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "strategies table is missing" in (result.stdout + result.stderr)
    assert _revision_rows(database_url) == []


def test_pre_alembic_schema_with_missing_column_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users DROP COLUMN role"))
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "users.role" in (result.stdout + result.stderr)
    assert _revision_rows(database_url) == []


@pytest.mark.parametrize(
    "alter_default",
    (
        "ALTER TABLE users ALTER COLUMN created_at DROP DEFAULT",
        "ALTER TABLE users ALTER COLUMN created_at "
        "SET DEFAULT TIMESTAMPTZ '2000-01-01 00:00:00+00'",
    ),
)
def test_pre_alembic_schema_with_changed_server_default_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
    alter_default: str,
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(alter_default))
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "users.created_at server default" in (result.stdout + result.stderr)
    assert _revision_rows(database_url) == []


def test_equivalent_current_timestamp_server_default_is_accepted(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users ALTER COLUMN created_at "
                    "SET DEFAULT CURRENT_TIMESTAMP"
                )
            )
    finally:
        engine.dispose()

    _run_alembic(database_url, "upgrade", "head")

    assert _revision_rows(database_url) == [HEAD_REVISION]


@pytest.mark.parametrize(
    ("table_name", "constraint_name", "include_new_tables"),
    (
        ("chat_messages", "ck_chat_messages_visible_role", False),
        ("ingestion_runs", "ck_ingestion_runs_status", True),
    ),
)
def test_pre_alembic_schema_with_missing_named_check_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
    table_name: str,
    constraint_name: str,
    include_new_tables: bool,
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(
        database_url,
        include_new_tables=include_new_tables,
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{constraint_name}"')
            )
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert constraint_name in (result.stdout + result.stderr)
    assert _revision_rows(database_url) == []


def test_pre_alembic_schema_with_changed_check_sql_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE chat_messages "
                    "DROP CONSTRAINT ck_chat_messages_visible_role, "
                    "ADD CONSTRAINT ck_chat_messages_visible_role "
                    "CHECK (role IN ('user', 'assistant', 'system'))"
                )
            )
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert "ck_chat_messages_visible_role" in (result.stdout + result.stderr)
    assert _revision_rows(database_url) == []


def test_future_orm_column_does_not_change_frozen_baseline_adoption(
    temporary_database: Callable[[], URL],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic.config import Config

    from alembic import command

    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    future_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(future_metadata)
    future_metadata.tables["users"].append_column(
        Column("future_profile", String(128), nullable=True)
    )
    monkeypatch.setattr(Base, "metadata", future_metadata)
    monkeypatch.setattr(
        settings,
        "database_url",
        database_url.render_as_string(hide_password=False),
    )
    monkeypatch.setattr(logging.config, "fileConfig", lambda *_args, **_kwargs: None)

    command.upgrade(Config(str(ALEMBIC_CONFIG)), "head")

    assert _revision_rows(database_url) == [HEAD_REVISION]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        assert "future_profile" not in {
            column["name"] for column in inspect(engine).get_columns("users")
        }
    finally:
        engine.dispose()
    _run_alembic(database_url, "upgrade", "head")


def test_pre_alembic_schema_with_wrong_hnsw_index_is_rejected_without_revision(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _create_pre_alembic_schema(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE INDEX {HNSW_INDEX} ON documents (id)"))
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "upgrade", "head", check=False)

    assert result.returncode != 0
    assert HNSW_INDEX in (result.stdout + result.stderr)
    assert "hnsw" in (result.stdout + result.stderr).lower()
    assert _revision_rows(database_url) == []


def test_alembic_check_reports_same_named_btree_instead_of_hnsw(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _run_alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"DROP INDEX {HNSW_INDEX}"))
            connection.execute(text(f"CREATE INDEX {HNSW_INDEX} ON documents (id)"))
    finally:
        engine.dispose()

    result = _run_alembic(database_url, "check", check=False)

    assert result.returncode != 0
    assert HNSW_INDEX in (result.stdout + result.stderr)


def test_concurrent_postgres_upgrades_are_serialized(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    processes = [
        subprocess.Popen(
            _alembic_command("upgrade", "head"),
            cwd=BACKEND_ROOT,
            env=_alembic_environment(database_url),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]

    results = [process.communicate(timeout=120) for process in processes]

    for process, (stdout, stderr) in zip(processes, results, strict=True):
        assert process.returncode == 0, stdout + stderr
    assert _revision_rows(database_url) == [HEAD_REVISION]
    _assert_baseline_objects(database_url)


def _assert_financial_pit_migration_preserves_legacy_rows(database_url: URL) -> None:
    _run_alembic(database_url, "upgrade", BASELINE_REVISION)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO financial_summaries "
                    "(code, report_date, eps, bps, roe, revenue, net_profit, "
                    "gross_margin, source, fetched_at) VALUES "
                    "(:code, :report_date, :eps, :bps, :roe, :revenue, "
                    ":net_profit, :gross_margin, :source, :fetched_at)"
                ),
                {
                    "code": "600000.SH",
                    "report_date": "2025-12-31",
                    "eps": "1.2300",
                    "bps": "10.5000",
                    "roe": "8.2500",
                    "revenue": "123456789.0000",
                    "net_profit": "9876543.0000",
                    "gross_margin": "20.5000",
                    "source": "legacy",
                    "fetched_at": "2026-03-10T02:00:00+00:00",
                },
            )
    finally:
        engine.dispose()

    _run_alembic(database_url, "upgrade", "head")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns(
            "financial_summaries"
        )}
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT code, report_date, eps, bps, roe, revenue, net_profit, "
                    "gross_margin, source, announced_at, available_at, fetched_at, "
                    "vintage FROM financial_summaries"
                )
            ).mappings().all()
    finally:
        engine.dispose()

    assert {
        "id",
        "announced_at",
        "available_at",
        "vintage",
    } <= columns
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "600000.SH"
    assert Decimal(str(row["eps"])) == Decimal("1.2300")
    assert Decimal(str(row["revenue"])) == Decimal("123456789.0000")
    assert row["announced_at"] is None
    assert row["available_at"] == row["fetched_at"]
    assert len(row["vintage"]) == 64


def test_postgres_financial_pit_migration_preserves_legacy_rows_and_values(
    temporary_database: Callable[[], URL],
) -> None:
    _assert_financial_pit_migration_preserves_legacy_rows(temporary_database())


def test_sqlite_financial_pit_migration_preserves_legacy_rows_and_values(
    tmp_path: Path,
) -> None:
    database_url = URL.create(
        "sqlite+pysqlite",
        database=str(tmp_path / "financial-pit.sqlite3"),
    )
    _assert_financial_pit_migration_preserves_legacy_rows(database_url)


def test_financial_pit_migration_canonicalizes_negative_zero() -> None:
    path = (
        ALEMBIC_DIR
        / "versions"
        / f"{FINANCIAL_PIT_REVISION}_financial_summary_pit.py"
    )
    spec = importlib.util.spec_from_file_location("financial_summary_pit_revision", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration._canonical_decimal(Decimal("-0.0000")) == "0"
    assert migration._canonical_decimal(Decimal("0.0000")) == "0"


def test_migrated_negative_zero_and_ingested_zero_share_one_vintage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = URL.create(
        "sqlite+pysqlite",
        database=str(tmp_path / "financial-negative-zero.sqlite3"),
    )
    _run_alembic(database_url, "upgrade", BASELINE_REVISION)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO financial_summaries "
                    "(code, report_date, eps, bps, roe, revenue, net_profit, "
                    "gross_margin, source, fetched_at) VALUES "
                    "('600000.SH', '2025-12-31', '-0.0000', '10.0000', "
                    "'8.0000', '1000.0000', '100.0000', '20.0000', "
                    "'legacy', '2026-03-10T02:00:00+00:00')"
                )
            )
    finally:
        engine.dispose()

    _run_alembic(database_url, "upgrade", "head")

    engine = create_engine(database_url, pool_pre_ping=True)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    provider = SimpleNamespace(
        name="test-financials",
        get_financials=lambda _code: [
            FinancialSummaryDTO(
                code="600000.SH",
                report_date=date(2025, 12, 31),
                eps=Decimal("0.0000"),
                bps=Decimal("10.0000"),
                roe=Decimal("8.0000"),
                revenue=Decimal("1000.0000"),
                net_profit=Decimal("100.0000"),
                gross_margin=Decimal("20.0000"),
            )
        ],
    )
    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(ingest, "_resolve", lambda *_args: provider)
    monkeypatch.setattr(
        ingest,
        "_now",
        lambda: datetime(2026, 3, 11, 2, tzinfo=UTC),
    )
    try:
        ingest.ingest_financials("600000.SH")
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM financial_summaries")
            ) == 1
            assert connection.scalar(
                text("SELECT count(DISTINCT vintage) FROM financial_summaries")
            ) == 1
    finally:
        engine.dispose()


def test_baseline_downgrade_is_explicitly_disabled(
    temporary_database: Callable[[], URL],
) -> None:
    database_url = temporary_database()
    _run_alembic(database_url, "upgrade", "head")

    result = _run_alembic(database_url, "downgrade", "base", check=False)

    assert result.returncode != 0
    assert "baseline downgrade is disabled" in (result.stdout + result.stderr).lower()
    _assert_baseline_objects(database_url)
