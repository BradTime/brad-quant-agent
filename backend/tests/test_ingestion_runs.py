"""回填运行快照：状态审计、CLI 失败码与回测数据质量闸。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from inspect import signature
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import cli, models
from app.backtest import data as data_module
from app.backtest import runner
from app.backtest.base import BacktestConfig
from app.backtest.data import Bar
from app.models.market import AdjustFactor, DailyBar, MinuteBar
from app.services import backtest_run, ingest, market


def _ingestion_run_model():
    model = getattr(models, "IngestionRun", None)
    assert model is not None, "应注册 IngestionRun ORM"
    return model


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_type="dual_ma",
        params={"fast": 2, "slow": 3},
        codes=["X"],
        start="2024-01-01",
        end="2024-01-03",
        initial_capital=100_000,
    )


def _bars(code: str = "X") -> list[Bar]:
    return [
        Bar(code, date(2024, 1, day), 10 + day, 10 + day, 10 + day, 10 + day, 100, 1_000)
        for day in range(1, 4)
    ]


def _provider_daily_bars() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            code="X",
            dt=datetime(2024, 1, day),
            open=10,
            high=11,
            low=9,
            close=10,
            volume=100,
            amount=1_000,
        )
        for day in range(1, 4)
    ]


def _snapshot_bars(code: str, frequency: str, start: str, end: str):
    quality = data_module.ingestion_run_quality(code, start, end, frequency)
    return _bars(), quality or "full"


def _dataset_audit(
    period: str,
    start: str,
    end: str,
    *,
    actual_start: str | None = None,
    actual_end: str | None = None,
) -> dict:
    return {
        "success": True,
        "rows": 1,
        "error": None,
        "period": period,
        "requested": {"start": start, "end": end},
        "actual": {
            "start": actual_start if actual_start is not None else start,
            "end": actual_end if actual_end is not None else end,
        },
    }


def _required_daily_audits(run_id: str, fetched_at: datetime) -> dict:
    stamp = fetched_at.isoformat()
    daily = _dataset_audit("1d", "2024-01-01", "2024-01-03")
    daily.update(
        {
            "rows": 3,
            "runId": run_id,
            "fetchedAtFloor": stamp,
            "fetchedAtWatermark": stamp,
        }
    )
    adjust = _dataset_audit(
        "adjust",
        "2024-01-01",
        "2024-01-03",
        actual_start=None,
        actual_end=None,
    )
    adjust.update(
        {
            "rows": 0,
            "actual": {"start": None, "end": None},
            "runId": run_id,
            "fetchedAtFloor": None,
            "fetchedAtWatermark": None,
        }
    )
    return {"daily": daily, "adjust": adjust}


def _required_minute_audits(
    run_id: str,
    fetched_at: datetime,
    start: str,
    end: str,
) -> dict:
    stamp = fetched_at.isoformat()
    minute = _dataset_audit("5m", start, end)
    minute.update(
        {
            "runId": run_id,
            "fetchedAtFloor": stamp,
            "fetchedAtWatermark": stamp,
            "previousClose": {
                "tradeDate": (
                    date.fromisoformat(start) - timedelta(days=1)
                ).isoformat(),
                "fetchedAt": stamp,
                "value": 9.0,
            },
        }
    )
    adjust = _dataset_audit("adjust", start, end)
    adjust.update(
        {
            "rows": 0,
            "actual": {"start": None, "end": None},
            "runId": run_id,
            "fetchedAtFloor": None,
            "fetchedAtWatermark": None,
        }
    )
    return {"minute:5": minute, "adjust": adjust}


@pytest.fixture
def ingestion_db(monkeypatch):
    run_model = _ingestion_run_model()
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        DailyBar.__table__,
        MinuteBar.__table__,
        AdjustFactor.__table__,
        run_model.__table__,
    ):
        table.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)
    def fake_dataset_range(
        _code, dataset, requested_start, requested_end, _period=None
    ):
        if dataset == "adjust":
            return {
                "start": None,
                "end": None,
                "fetchedAtFloor": None,
                "fetchedAtWatermark": None,
            }
        stamp = datetime.now(UTC).isoformat()
        return {
            "start": requested_start,
            "end": requested_end,
            "fetchedAtFloor": stamp,
            "fetchedAtWatermark": stamp,
        }

    monkeypatch.setattr(
        ingest,
        "_dataset_actual_range",
        fake_dataset_range,
        raising=False,
    )
    try:
        yield test_session
    finally:
        engine.dispose()


@pytest.fixture
def audited_ingestion_db(monkeypatch):
    run_model = _ingestion_run_model()
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        DailyBar.__table__,
        MinuteBar.__table__,
        AdjustFactor.__table__,
        run_model.__table__,
    ):
        table.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)

    def sqlite_upsert(session, model, rows, index_elements, update_cols):
        for row in rows:
            key_values = tuple(row[column] for column in index_elements)
            key = key_values[0] if len(key_values) == 1 else key_values
            existing = session.get(model, key)
            if existing is None:
                session.add(model(**row))
            else:
                for column in update_cols:
                    setattr(existing, column, row[column])
        session.flush()
        return len(rows)

    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)
    monkeypatch.setattr(ingest, "_upsert", sqlite_upsert)
    try:
        yield test_session
    finally:
        engine.dispose()


def _patch_optional_tasks(monkeypatch, *, rows: int = 1) -> None:
    monkeypatch.setattr(ingest, "ingest_capital_flow", lambda *args, **kwargs: rows)
    monkeypatch.setattr(ingest, "ingest_financials", lambda *args, **kwargs: rows)
    monkeypatch.setattr(ingest, "ingest_news", lambda *args, **kwargs: rows)


def _insert_run(
    session_factory,
    *,
    status: str,
    started_at: datetime,
    start: date = date(2024, 1, 1),
    end: date = date(2024, 1, 3),
    datasets: dict | None = None,
    completed_at: datetime | None = None,
) -> None:
    run_model = _ingestion_run_model()
    run_id = f"{status}-{started_at.timestamp()}"
    if datasets is None:
        datasets = _required_daily_audits(run_id, started_at)
        if status != "ready":
            datasets["daily"].update(
                {
                    "success": False if status != "running" else None,
                    "rows": 0,
                    "error": "daily incomplete",
                    "fetchedAtFloor": None,
                    "fetchedAtWatermark": None,
                }
            )
    with session_factory() as session:
        for dataset, audit in datasets.items():
            if not isinstance(audit, dict) or audit.get("success") is not True:
                continue
            watermark = audit.get("fetchedAtWatermark")
            actual = audit.get("actual")
            if not watermark or not isinstance(actual, dict):
                continue
            stamp = datetime.fromisoformat(watermark)
            actual_start = date.fromisoformat(str(actual["start"])[:10])
            actual_end = date.fromisoformat(str(actual["end"])[:10])
            if dataset == "daily":
                for trade_date in {actual_start, actual_end}:
                    row = session.get(DailyBar, ("X", trade_date))
                    if row is None:
                        session.add(
                            DailyBar(
                                code="X",
                                trade_date=trade_date,
                                open=10,
                                high=11,
                                low=9,
                                close=10,
                                volume=100,
                                amount=1_000,
                                fetched_at=stamp,
                            )
                        )
                    else:
                        row.fetched_at = stamp
            elif dataset.startswith("minute:"):
                period = dataset.removeprefix("minute:")
                for trade_date in {actual_start, actual_end}:
                    dt = datetime.combine(trade_date, time(9, 35))
                    row = session.get(MinuteBar, ("X", dt, period))
                    if row is None:
                        session.add(
                            MinuteBar(
                                code="X",
                                dt=dt,
                                period=period,
                                open=10,
                                high=11,
                                low=9,
                                close=10,
                                volume=100,
                                amount=1_000,
                                fetched_at=stamp,
                            )
                        )
                    else:
                        row.fetched_at = stamp
                dependency = audit.get("previousClose")
                if isinstance(dependency, dict):
                    previous_date = date.fromisoformat(dependency["tradeDate"])
                    previous = session.get(DailyBar, ("X", previous_date))
                    if previous is None:
                        session.add(
                            DailyBar(
                                code="X",
                                trade_date=previous_date,
                                open=dependency["value"],
                                high=dependency["value"],
                                low=dependency["value"],
                                close=dependency["value"],
                                volume=100,
                                amount=900,
                                fetched_at=datetime.fromisoformat(
                                    dependency["fetchedAt"]
                                ),
                            )
                        )
                    else:
                        previous.close = dependency["value"]
                        previous.fetched_at = datetime.fromisoformat(
                            dependency["fetchedAt"]
                        )
        session.add(
            run_model(
                id=run_id,
                code="X",
                start_date=start,
                end_date=end,
                status=status,
                datasets_json=json.dumps(datasets),
                error_json="{}",
                started_at=started_at,
                completed_at=(
                    completed_at
                    if completed_at is not None
                    else (started_at if status != "running" else None)
                ),
            )
        )
        session.commit()


def test_ingestion_run_model_is_registered_with_required_columns():
    run_model = _ingestion_run_model()

    assert set(run_model.__table__.columns.keys()) == {
        "id",
        "code",
        "start_date",
        "end_date",
        "status",
        "datasets_json",
        "error_json",
        "started_at",
        "completed_at",
    }


def test_daily_success_adjust_error_creates_partial_run_and_redacts_secret(
    ingestion_db, monkeypatch, caplog
):
    monkeypatch.setattr(ingest, "ingest_daily", lambda *args, **kwargs: 3)

    def fail_adjust(*args, **kwargs):
        raise RuntimeError(
            "provider failed api_key=super-secret "
            "Authorization: Bearer bearer-secret password=hunter2"
        )

    monkeypatch.setattr(ingest, "ingest_adjust", fail_adjust)
    _patch_optional_tasks(monkeypatch)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with ingestion_db() as session:
        row = session.execute(select(run_model)).scalar_one()
        datasets = json.loads(row.datasets_json)
        errors = json.loads(row.error_json)

    assert row.status == "partial"
    assert row.completed_at is not None
    assert datasets["daily"]["success"] is True
    assert datasets["daily"]["rows"] == 3
    assert datasets["daily"]["error"] is None
    assert datasets["daily"]["period"] == "1d"
    assert datasets["daily"]["requested"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
    }
    assert datasets["adjust"]["success"] is False
    assert datasets["adjust"]["rows"] == 0
    assert datasets["adjust"]["error"]
    assert errors["adjust"] == datasets["adjust"]["error"]
    assert stats["errors"] == 1
    assert stats["runs"][0]["status"] == "partial"
    assert stats["runs"][0]["failedDatasets"] == ["adjust"]
    rendered = json.dumps({"datasets": datasets, "errors": errors}, ensure_ascii=False)
    assert "super-secret" not in rendered
    assert "bearer-secret" not in rendered
    assert "hunter2" not in rendered
    assert "super-secret" not in caplog.text


def test_all_tasks_success_creates_ready_run_and_zero_adjust_is_success(ingestion_db, monkeypatch):
    monkeypatch.setattr(ingest, "ingest_daily", lambda *args, **kwargs: 3)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    _patch_optional_tasks(monkeypatch, rows=0)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with ingestion_db() as session:
        row = session.execute(select(run_model)).scalar_one()
        datasets = json.loads(row.datasets_json)

    assert row.status == "ready"
    assert datasets["adjust"]["success"] is True
    assert datasets["adjust"]["rows"] == 0
    assert datasets["adjust"]["error"] is None
    assert datasets["adjust"]["actual"] == {"start": None, "end": None}
    assert stats["errors"] == 0
    assert stats["runs"][0]["status"] == "ready"


@pytest.mark.parametrize(
    ("ex_date", "factor"),
    [
        (None, 1.0),
        (date(2024, 1, 2), float("inf")),
        (date(2024, 1, 2), 0.0),
        (date(2024, 1, 2), -1.0),
    ],
)
def test_adjust_rejects_invalid_dates_and_non_positive_or_non_finite_factors(
    monkeypatch, ex_date, factor
):
    provider = SimpleNamespace(
        name="fake",
        get_adjust_factors=lambda *args: [
            SimpleNamespace(
                code="X",
                ex_date=ex_date,
                adjust_factor=factor,
                fore_adjust_factor=1.0,
                back_adjust_factor=1.0,
            )
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    with pytest.raises(ValueError, match="复权"):
        ingest.ingest_adjust("X", "2024-01-01", "2024-01-03")


def test_cli_backfill_returns_one_and_lists_partial_dataset(monkeypatch, capsys):
    monkeypatch.setattr(
        ingest,
        "backfill_codes",
        lambda *args, **kwargs: {
            "daily": 3,
            "adjust": 0,
            "capital_flow": 0,
            "financials": 0,
            "news": 0,
            "minute": 0,
            "errors": 1,
            "runs": [
                {
                    "code": "X",
                    "status": "partial",
                    "failedDatasets": ["adjust"],
                }
            ],
        },
    )

    exit_code = cli.main(
        [
            "backfill",
            "--codes",
            "X",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "X" in output
    assert "partial" in output
    assert "adjust" in output
    assert "✅ 回填完成" not in output


@pytest.mark.parametrize("status", ["partial", "failed", "running"])
def test_latest_non_ready_run_marks_partial_ingestion_and_rejects_backtest(
    ingestion_db, monkeypatch, status
):
    _insert_run(
        ingestion_db,
        status=status,
        started_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
    monkeypatch.setattr(runner, "load_bars_with_quality", _snapshot_bars)

    result = runner.run_backtest(_config())

    assert result["dataQuality"] == {"X": "partial_ingestion"}
    assert "部分回填" in result["error"]


def test_new_ready_run_supersedes_old_partial_and_allows_backtest(ingestion_db, monkeypatch):
    _insert_run(
        ingestion_db,
        status="partial",
        started_at=datetime(2024, 1, 4, tzinfo=UTC),
    )
    _insert_run(
        ingestion_db,
        status="ready",
        started_at=datetime(2024, 1, 5, tzinfo=UTC),
    )
    monkeypatch.setattr(runner, "load_bars_with_quality", _snapshot_bars)
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda *args: ([], "untracked"),
    )

    result = runner.run_backtest(_config())

    assert "error" not in result
    assert result["dataQuality"]["X"] == "full"


def test_no_ingestion_run_is_untracked_but_allowed_and_disclosed(ingestion_db, monkeypatch):
    monkeypatch.setattr(runner, "load_bars_with_quality", _snapshot_bars)
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda *args: ([], "untracked"),
    )

    result = runner.run_backtest(_config())

    assert "error" not in result
    assert result["dataQuality"]["X"] == "untracked"


def test_historical_database_without_ingestion_table_is_untracked(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)
    try:
        assert (
            data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03")
            == "untracked"
        )
    finally:
        engine.dispose()


def test_new_narrow_partial_after_covering_ready_blocks_request(ingestion_db):
    ready_at = datetime(2024, 1, 4, tzinfo=UTC)
    _insert_run(
        ingestion_db,
        status="ready",
        started_at=ready_at,
        completed_at=ready_at,
    )
    _insert_run(
        ingestion_db,
        status="partial",
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        started_at=datetime(2024, 1, 5, tzinfo=UTC),
    )

    quality = data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03")

    assert quality == "partial_ingestion"


def test_backfill_records_requested_actual_ranges_and_minute_period(
    ingestion_db, monkeypatch
):
    monkeypatch.setattr(ingest, "ingest_daily", lambda *args, **kwargs: 3)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_minute", lambda *args, **kwargs: 2)
    _patch_optional_tasks(monkeypatch, rows=0)

    ingest.backfill_codes(
        ["X"],
        "2024-01-01",
        "2024-01-03",
        minute_periods=["5"],
        minute_start="2024-01-02",
    )

    run_model = _ingestion_run_model()
    with ingestion_db() as session:
        datasets = json.loads(session.execute(select(run_model.datasets_json)).scalar_one())

    assert datasets["daily"]["period"] == "1d"
    assert datasets["daily"]["requested"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
    }
    assert datasets["daily"]["actual"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
    }
    assert datasets["adjust"]["requested"] == {
        "start": "2024-01-01",
        "end": "2024-01-03",
    }
    assert datasets["adjust"]["actual"] == {"start": None, "end": None}
    assert datasets["minute:5"]["period"] == "5m"
    assert datasets["minute:5"]["requested"] == {
        "start": "2024-01-02",
        "end": "2024-01-03",
    }
    assert datasets["minute:5"]["actual"] == {
        "start": "2024-01-02",
        "end": "2024-01-03",
    }


def test_daily_only_ready_run_does_not_track_minute_frequency(ingestion_db):
    quality_fn = data_module.ingestion_run_quality
    assert "frequency" in signature(quality_fn).parameters
    _insert_run(
        ingestion_db,
        status="ready",
        started_at=datetime(2024, 1, 4, tzinfo=UTC),
    )

    quality = quality_fn("X", "2024-01-01", "2024-01-03", frequency="5m")

    assert quality == "untracked"


def test_minute_ready_run_must_cover_requested_window(ingestion_db):
    quality_fn = data_module.ingestion_run_quality
    assert "frequency" in signature(quality_fn).parameters
    started_at = datetime(2024, 1, 4, tzinfo=UTC)
    run_id = f"ready-{started_at.timestamp()}"
    datasets = _required_minute_audits(
        run_id,
        started_at,
        "2024-01-02",
        "2024-01-03",
    )
    _insert_run(
        ingestion_db,
        status="ready",
        started_at=started_at,
        datasets=datasets,
    )

    quality = quality_fn("X", "2024-01-01", "2024-01-03", frequency="5m")

    assert quality == "untracked"


def test_complete_minute_ready_run_tracks_matching_frequency(ingestion_db):
    quality_fn = data_module.ingestion_run_quality
    assert "frequency" in signature(quality_fn).parameters
    started_at = datetime(2024, 1, 4, tzinfo=UTC)
    run_id = f"ready-{started_at.timestamp()}"
    datasets = _required_minute_audits(
        run_id,
        started_at,
        "2024-01-01",
        "2024-01-03",
    )
    _insert_run(
        ingestion_db,
        status="ready",
        started_at=started_at,
        datasets=datasets,
    )

    quality = quality_fn("X", "2024-01-01", "2024-01-03", frequency="5m")

    assert quality is None


def test_same_code_backfills_are_serialized_from_run_creation_to_completion(
    tmp_path, monkeypatch
):
    run_model = _ingestion_run_model()
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'ingestion-lock.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    run_model.__table__.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(
        ingest,
        "_dataset_actual_range",
        lambda _code, _dataset, requested_start, requested_end, _period=None: {
            "start": requested_start,
            "end": requested_end,
        },
        raising=False,
    )

    calls = 0
    calls_guard = Lock()
    first_daily_started = Event()
    second_daily_started = Event()
    release_daily = Event()
    second_call_started = Event()

    def daily(*args, **kwargs):
        nonlocal calls
        with calls_guard:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_daily_started.set()
        else:
            second_daily_started.set()
        assert release_daily.wait(3)
        return 1

    monkeypatch.setattr(ingest, "ingest_daily", daily)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    _patch_optional_tasks(monkeypatch, rows=0)

    def backfill():
        return ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    def second_backfill():
        second_call_started.set()
        return backfill()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(backfill)
            assert first_daily_started.wait(2)
            second = pool.submit(second_backfill)
            assert second_call_started.wait(2)
            serialized = not second_daily_started.wait(0.2)
            with test_session() as session:
                visible_runs = len(session.execute(select(run_model)).scalars().all())
            release_daily.set()
            first.result(timeout=3)
            second.result(timeout=3)
    finally:
        release_daily.set()
        engine.dispose()

    assert serialized
    assert visible_runs == 1


def test_postgresql_advisory_lock_wraps_critical_section(monkeypatch):
    lock_context = getattr(ingest, "_code_backfill_lock", None)
    assert lock_context is not None, "应提供同 code 进程锁与 PostgreSQL advisory lock"
    statements: list[str] = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params=None):
            statements.append(str(statement))

    monkeypatch.setattr(ingest, "SessionLocal", FakeSession)

    with lock_context("X"):
        statements.append("critical-section")

    assert "pg_advisory_lock" in statements[0]
    assert statements[1] == "critical-section"
    assert "pg_advisory_unlock" in statements[2]


def test_data_and_ingestion_quality_share_one_repeatable_snapshot(tmp_path, monkeypatch):
    loader = getattr(data_module, "load_bars_with_quality", None)
    quality_in_session = getattr(data_module, "_ingestion_run_quality_in_session", None)
    assert loader is not None, "应提供单 Session 行情+质量加载 helper"
    assert quality_in_session is not None

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'snapshot.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    DailyBar.__table__.create(bind=engine)
    AdjustFactor.__table__.create(bind=engine)
    _ingestion_run_model().__table__.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)

    ready_at = datetime(2024, 1, 4, tzinfo=UTC)
    with test_session.begin() as session:
        session.add_all(
            [
                DailyBar(
                    code="X",
                    trade_date=date(2024, 1, day),
                    open=10 + day,
                    high=10 + day,
                    low=10 + day,
                    close=10 + day,
                    volume=100,
                    amount=1_000,
                    fetched_at=ready_at,
                )
                for day in range(1, 4)
            ]
            + [
                AdjustFactor(
                    code="X",
                    ex_date=date(2024, 1, 1),
                    adjust_factor=1,
                    fore_adjust_factor=1,
                    back_adjust_factor=1,
                    fetched_at=ready_at,
                )
            ]
        )
    run_id = f"ready-{ready_at.timestamp()}"
    datasets = _required_daily_audits(run_id, ready_at)
    datasets["adjust"].update(
        {
            "rows": 1,
            "actual": {"start": "2024-01-01", "end": "2024-01-01"},
            "fetchedAtFloor": ready_at.isoformat(),
            "fetchedAtWatermark": ready_at.isoformat(),
        }
    )
    _insert_run(
        test_session,
        status="ready",
        started_at=ready_at,
        completed_at=ready_at,
        datasets=datasets,
    )

    quality_query_reached = Event()
    allow_quality_query = Event()

    def delayed_quality(*args, **kwargs):
        quality_query_reached.set()
        assert allow_quality_query.wait(3)
        return quality_in_session(*args, **kwargs)

    monkeypatch.setattr(data_module, "_ingestion_run_quality_in_session", delayed_quality)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(loader, "X", "1d", "2024-01-01", "2024-01-03")
            assert quality_query_reached.wait(2)
            _insert_run(
                test_session,
                status="partial",
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                started_at=datetime(2024, 1, 5, tzinfo=UTC),
            )
            allow_quality_query.set()
            bars, quality = future.result(timeout=3)
    finally:
        allow_quality_query.set()
        engine.dispose()

    assert len(bars) == 3
    assert quality == "full"


@pytest.mark.parametrize(
    ("payload", "secret_values"),
    [
        (
            '{"api_key": "json-key", "access_token": "json-access", '
            '"X-API-Key": "x-api-key", "authorization": "Bearer bearer-json", '
            '"password": "json-password", "secret": "json-secret", '
            '"token": "json-token"}',
            (
                "json-key",
                "json-access",
                "x-api-key",
                "bearer-json",
                "json-password",
                "json-secret",
                "json-token",
            ),
        ),
        (
            "{'api_key': 'python-key', 'authorization': 'Basic basic-python', "
            "'password': 'python-password', 'token': 'python-token'}",
            ("python-key", "basic-python", "python-password", "python-token"),
        ),
    ],
)
def test_error_sanitizer_redacts_quoted_mapping_values_and_auth_schemes(
    payload, secret_values
):
    summary = ingest._sanitize_error(RuntimeError(payload))

    assert "[REDACTED]" in summary
    for value in secret_values:
        assert value not in summary


def test_independent_daily_ingest_creates_audited_run(audited_ingestion_db, monkeypatch):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: _provider_daily_bars(),
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    rows = ingest.ingest_daily("X", "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with audited_ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        audit = json.loads(run.datasets_json)["daily"]
    assert rows == 3
    assert run.status == "ready"
    assert audit["success"] is True
    assert audit["runId"] == run.id
    assert audit["fetchedAtWatermark"]


def test_independent_daily_cli_creates_audited_run(
    audited_ingestion_db, monkeypatch, capsys
):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: _provider_daily_bars(),
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    exit_code = cli.main(
        [
            "ingest-daily",
            "--code",
            "X",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
        ]
    )

    assert exit_code == 0
    assert "日K落库 3 条" in capsys.readouterr().out
    with audited_ingestion_db() as session:
        assert len(session.execute(select(_ingestion_run_model())).scalars().all()) == 1


def test_independent_minute_ingest_creates_audited_run(audited_ingestion_db, monkeypatch):
    previous_fetched_at = datetime(2024, 1, 1, 16, tzinfo=UTC)
    with audited_ingestion_db.begin() as session:
        session.add(
            DailyBar(
                code="X",
                trade_date=date(2024, 1, 1),
                open=9,
                high=9,
                low=9,
                close=9,
                volume=100,
                amount=900,
                fetched_at=previous_fetched_at,
            )
        )
    provider = SimpleNamespace(
        name="fake",
        get_minute_bars=lambda *args, **kwargs: [
            SimpleNamespace(
                code="X",
                dt=datetime(2024, 1, 2, 9, 35),
                period="5",
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
                amount=1_000,
            )
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    rows = ingest.ingest_minute("X", "5", "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with audited_ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        audit = json.loads(run.datasets_json)["minute:5"]
    assert rows == 1
    assert run.status == "ready"
    assert audit["period"] == "5m"
    assert audit["runId"] == run.id
    assert audit["previousClose"] == {
        "tradeDate": "2024-01-01",
        "fetchedAt": previous_fetched_at.replace(tzinfo=None).isoformat(),
        "value": 9.0,
    }


def test_independent_zero_adjust_is_audited_success(audited_ingestion_db, monkeypatch):
    prior_fetched_at = datetime(2023, 12, 20, 16, tzinfo=UTC)
    with audited_ingestion_db.begin() as session:
        session.add(
            AdjustFactor(
                code="X",
                ex_date=date(2023, 12, 20),
                adjust_factor=1,
                fore_adjust_factor=1,
                back_adjust_factor=1,
                fetched_at=prior_fetched_at,
            )
        )
    provider = SimpleNamespace(name="fake", get_adjust_factors=lambda *args, **kwargs: [])
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    rows = ingest.ingest_adjust("X", "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with audited_ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        audit = json.loads(run.datasets_json)["adjust"]
    assert rows == 0
    assert run.status == "ready"
    assert audit["success"] is True
    assert audit["runId"] == run.id
    assert audit["actual"] == {
        "start": "2023-12-20",
        "end": "2023-12-20",
    }
    assert audit["fetchedAtWatermark"] == prior_fetched_at.replace(
        tzinfo=None
    ).isoformat()


def test_backfill_reuses_active_run_for_daily_and_adjust(
    audited_ingestion_db, monkeypatch
):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: _provider_daily_bars(),
        get_adjust_factors=lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    _patch_optional_tasks(monkeypatch, rows=0)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with audited_ingestion_db() as session:
        runs = list(session.execute(select(run_model)).scalars().all())
    assert len(runs) == 1
    assert stats["runs"][0]["id"] == runs[0].id
    datasets = json.loads(runs[0].datasets_json)
    assert datasets["daily"]["runId"] == runs[0].id
    assert datasets["adjust"]["runId"] == runs[0].id


def test_independent_daily_write_invalidates_old_ready_watermark(
    audited_ingestion_db, monkeypatch
):
    old_time = datetime(2024, 1, 4, tzinfo=UTC)
    run_id = f"ready-{old_time.timestamp()}"
    with audited_ingestion_db.begin() as session:
        session.add_all(
            [
                DailyBar(
                    code="X",
                    trade_date=date(2024, 1, day),
                    open=10,
                    high=11,
                    low=9,
                    close=10,
                    volume=100,
                    amount=1_000,
                    fetched_at=old_time,
                )
                for day in range(1, 4)
            ]
        )
    _insert_run(
        audited_ingestion_db,
        status="ready",
        started_at=old_time,
        completed_at=old_time,
        datasets=_required_daily_audits(run_id, old_time),
    )
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: _provider_daily_bars(),
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_now", lambda: datetime(2024, 1, 5, tzinfo=UTC))

    ingest.ingest_daily("X", "2024-01-01", "2024-01-03")

    assert (
        data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03")
        == "partial_ingestion"
    )


def test_refresh_stock_routes_required_writes_through_backfill(monkeypatch):
    calls: list[tuple[list[str], str, str]] = []

    def fake_backfill(codes, start, end, *args, **kwargs):
        calls.append((codes, start, end))
        return {
            "daily": 3,
            "adjust": 0,
            "capital_flow": 0,
            "financials": 0,
            "news": 0,
            "minute": 0,
            "errors": 0,
            "runs": [
                {
                    "id": "run-1",
                    "code": codes[0],
                    "status": "ready",
                    "failedDatasets": [],
                }
            ],
        }

    monkeypatch.setattr(ingest, "backfill_codes", fake_backfill)
    monkeypatch.setattr(
        ingest,
        "ingest_daily",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("bypassed backfill")),
    )
    monkeypatch.setattr(ingest, "ingest_capital_flow", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_financials", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_news", lambda *args, **kwargs: 0)

    result = market.refresh_stock("X", daily_days=3)

    assert len(calls) == 1
    assert result["runStatus"] == "ready"


def test_news_failure_does_not_block_successful_daily_dependencies(
    audited_ingestion_db, monkeypatch
):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: _provider_daily_bars(),
        get_adjust_factors=lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "ingest_capital_flow", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_financials", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        ingest,
        "ingest_news",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("news unavailable")),
    )

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    assert stats["runs"][0]["status"] == "partial"
    assert data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03") is None


def test_financial_decimal_overflow_marks_backfill_partial(
    ingestion_db, monkeypatch
):
    financial = SimpleNamespace(
        code="X",
        report_date=date(2024, 1, 3),
        announced_at=None,
        available_at=None,
        announced_at_precision=None,
        eps=Decimal("1"),
        bps=Decimal("10"),
        roe=Decimal("8"),
        revenue=Decimal("100000000000000000000"),
        net_profit=Decimal("100"),
        gross_margin=Decimal("20"),
    )
    provider = SimpleNamespace(
        name="fake",
        get_financials=lambda *args, **kwargs: [financial],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "ingest_daily", lambda *args, **kwargs: 3)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_capital_flow", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_news", lambda *args, **kwargs: 0)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        datasets = json.loads(run.datasets_json)
    assert run.status == "partial"
    assert datasets["financials"]["success"] is False
    assert "revenue" in datasets["financials"]["error"]
    assert "precision" in datasets["financials"]["error"]
    assert stats["runs"][0]["failedDatasets"] == ["financials"]


def test_zero_daily_rows_marks_backfill_partial(ingestion_db, monkeypatch):
    monkeypatch.setattr(ingest, "ingest_daily", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    _patch_optional_tasks(monkeypatch, rows=0)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        daily = json.loads(run.datasets_json)["daily"]
    assert run.status == "partial"
    assert daily["success"] is False
    assert stats["errors"] == 1


def test_zero_daily_rows_fails_independent_ingest(audited_ingestion_db, monkeypatch):
    empty_error = getattr(ingest, "EmptyDatasetError", None)
    assert empty_error is not None, "应为 daily/minute 零行提供审计失败异常"
    provider = SimpleNamespace(name="fake", get_daily_bars=lambda *args, **kwargs: [])
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)

    with pytest.raises(empty_error):
        ingest.ingest_daily("X", "2024-01-01", "2024-01-03")

    run_model = _ingestion_run_model()
    with audited_ingestion_db() as session:
        run = session.execute(select(run_model)).scalar_one()
        daily = json.loads(run.datasets_json)["daily"]
    assert run.status == "failed"
    assert daily["success"] is False


def test_untracked_benchmark_is_explicitly_disclosed(monkeypatch):
    benchmark_loader = getattr(runner, "load_benchmark_with_quality", None)
    assert benchmark_loader is not None, "基准必须走带质量的一致快照加载"
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda config: ({"X": _bars()}, {"X": "full"}),
    )
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (_bars(), "untracked"),
    )

    result = runner.run_backtest(_config())

    assert "error" not in result
    assert result["dataQuality"]["000300.SH:benchmark"] == "untracked"
    assert result["ruleQuality"]["benchmarkData"] == "untracked"


def test_partial_benchmark_is_rejected(monkeypatch):
    benchmark_loader = getattr(runner, "load_benchmark_with_quality", None)
    assert benchmark_loader is not None, "基准必须走带质量的一致快照加载"
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda config: ({"X": _bars()}, {"X": "full"}),
    )
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (_bars(), "partial_ingestion"),
    )

    result = runner.run_backtest(_config())

    assert "基准" in result["error"]
    assert result["dataQuality"]["000300.SH:benchmark"] == "partial_ingestion"


def test_grid_search_discloses_untracked_benchmark(monkeypatch):
    code = "600000.SH"
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda config: ({code: _bars(code)}, {code: "full"}),
    )
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (_bars(), "untracked"),
    )

    config = _config()
    config.codes = [code]
    result = backtest_run.grid_search(config, {"fast": [2]})

    assert result["dataQuality"]["000300.SH:benchmark"] == "untracked"
    assert result["ruleQuality"]["benchmarkData"] == "untracked"


def test_grid_search_rejects_partial_benchmark(monkeypatch):
    code = "600000.SH"
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda config: ({code: _bars(code)}, {code: "full"}),
    )
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (_bars(), "partial_ingestion"),
    )

    config = _config()
    config.codes = [code]
    result = backtest_run.grid_search(config, {"fast": [2]})

    assert "基准" in result["error"]
    assert result["dataQuality"]["000300.SH:benchmark"] == "partial_ingestion"


def test_pre_start_adjust_factor_write_invalidates_ready_watermark(
    audited_ingestion_db, monkeypatch
):
    ready_at = datetime(2024, 1, 4, tzinfo=UTC)
    prior_fetched_at = datetime(2023, 12, 20, 16, tzinfo=UTC)
    run_id = f"ready-{ready_at.timestamp()}"
    datasets = _required_daily_audits(run_id, ready_at)
    datasets["adjust"].update(
        {
            "rows": 1,
            "actual": {"start": "2023-12-20", "end": "2023-12-20"},
            "fetchedAtFloor": prior_fetched_at.isoformat(),
            "fetchedAtWatermark": prior_fetched_at.isoformat(),
        }
    )
    with audited_ingestion_db.begin() as session:
        session.add(
            AdjustFactor(
                code="X",
                ex_date=date(2023, 12, 20),
                adjust_factor=1,
                fore_adjust_factor=1,
                back_adjust_factor=1,
                fetched_at=prior_fetched_at,
            )
        )
    _insert_run(
        audited_ingestion_db,
        status="ready",
        started_at=ready_at,
        completed_at=ready_at,
        datasets=datasets,
    )
    assert data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03") is None

    provider = SimpleNamespace(
        name="fake",
        get_adjust_factors=lambda *args, **kwargs: [
            SimpleNamespace(
                code="X",
                ex_date=date(2023, 12, 20),
                adjust_factor=1.1,
                fore_adjust_factor=1.1,
                back_adjust_factor=1.1,
            )
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_now", lambda: datetime(2024, 1, 5, tzinfo=UTC))

    ingest.ingest_adjust("X", "2023-12-01", "2023-12-31")

    assert (
        data_module.ingestion_run_quality("X", "2024-01-01", "2024-01-03")
        == "partial_ingestion"
    )


def test_minute_previous_close_write_invalidates_ready_dependency(
    audited_ingestion_db, monkeypatch
):
    ready_at = datetime(2024, 1, 4, tzinfo=UTC)
    run_id = f"ready-{ready_at.timestamp()}"
    datasets = _required_minute_audits(
        run_id,
        ready_at,
        "2024-01-02",
        "2024-01-03",
    )
    datasets["minute:5"]["previousClose"] = {
        "tradeDate": "2024-01-01",
        "fetchedAt": ready_at.isoformat(),
        "value": 9.0,
    }
    with audited_ingestion_db.begin() as session:
        session.add(
            DailyBar(
                code="X",
                trade_date=date(2024, 1, 1),
                open=9,
                high=9,
                low=9,
                close=9,
                volume=100,
                amount=900,
                fetched_at=ready_at,
            )
        )
    _insert_run(
        audited_ingestion_db,
        status="ready",
        started_at=ready_at,
        completed_at=ready_at,
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        datasets=datasets,
    )
    assert (
        data_module.ingestion_run_quality(
            "X",
            "2024-01-02",
            "2024-01-03",
            frequency="5m",
        )
        is None
    )

    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: [
            SimpleNamespace(
                code="X",
                dt=datetime(2024, 1, 1),
                open=8,
                high=8,
                low=8,
                close=8,
                volume=100,
                amount=800,
            )
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_now", lambda: datetime(2024, 1, 5, tzinfo=UTC))

    ingest.ingest_daily("X", "2024-01-01", "2024-01-01")

    assert (
        data_module.ingestion_run_quality(
            "X",
            "2024-01-02",
            "2024-01-03",
            frequency="5m",
        )
        == "partial_ingestion"
    )


def test_benchmark_loader_uses_audited_daily_quality_gate(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_loader(code, frequency, start, end):
        calls.append((code, frequency))
        return [], "partial_ingestion"

    monkeypatch.setattr(runner, "load_bars_with_quality", fake_loader)

    bars, quality = runner.load_benchmark_with_quality("2024-01-01", "2024-01-03")

    assert bars == []
    assert quality == "partial_ingestion"
    assert calls == [("000300.SH", "1d")]

