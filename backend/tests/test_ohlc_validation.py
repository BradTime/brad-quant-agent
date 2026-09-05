"""P0 OHLC validation: reject bad bars without fabricating zero values."""

from __future__ import annotations

import json
import traceback
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import market as market_api
from app.backtest import data as data_module
from app.backtest import runner
from app.backtest.base import BacktestConfig
from app.core.ohlc import InvalidOHLCError, validate_ohlc
from app.models.ingestion import IngestionRun
from app.models.market import AdjustFactor, DailyBar, MinuteBar
from app.providers.base import BarDTO, QuoteDTO
from app.services import backtest_run, ingest, market


@pytest.fixture
def ohlc_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        DailyBar.__table__,
        MinuteBar.__table__,
        AdjustFactor.__table__,
        IngestionRun.__table__,
    ):
        table.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)
    monkeypatch.setattr(market, "SessionLocal", test_session)
    try:
        yield test_session
    finally:
        engine.dispose()


def _provider_bar(*, dt: datetime, **overrides):
    values = {
        "code": "X",
        "dt": dt,
        "period": "5",
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 100.0,
        "amount": 1_000.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _fake_upsert(session, model, rows, index_elements, update_cols):
    """Exercise commit behavior without requiring PostgreSQL in this unit test."""
    for values in rows:
        key = tuple(values[column] for column in index_elements)
        identity = key[0] if len(key) == 1 else key
        row = session.get(model, identity)
        if row is None:
            session.add(model(**values))
            continue
        for column in update_cols:
            setattr(row, column, values[column])
    return len(rows)


def test_invalid_ohlc_traceback_never_contains_sensitive_raw_value():
    sensitive = "api_key=" + "super-secret"
    with pytest.raises(InvalidOHLCError) as caught:
        validate_ohlc(
            open_value=sensitive,
            high_value=12,
            low_value=9,
            close_value=11,
            code="X",
            bar_time=datetime(2024, 1, 1),
        )

    rendered = "".join(
        traceback.format_exception(caught.type, caught.value, caught.tb)
    )
    assert "super-secret" not in rendered
    assert "api_key" not in rendered
    assert "reason=non_numeric_open" in rendered


@pytest.mark.parametrize(
    "field",
    ["open", "high", "low", "close", "volume", "amount"],
)
@pytest.mark.parametrize(
    "invalid",
    [True, float("nan"), float("inf")],
    ids=["bool", "nan", "inf"],
)
def test_bar_dto_rejects_bool_nan_and_inf_before_float_coercion(field, invalid):
    values = {
        "code": "X",
        "dt": datetime(2024, 1, 1),
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "volume": 100,
        "amount": 1_000,
    }
    values[field] = invalid

    with pytest.raises(ValidationError):
        BarDTO(**values)


def test_real_bar_dto_blocks_invalid_ingest_before_upsert(
    ohlc_db,
    monkeypatch,
):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: [
            BarDTO(
                code="X",
                dt=datetime(2024, 1, 1),
                open=True,
                high=2,
                low=0.5,
                close=1.5,
                volume=100,
                amount=1_000,
            )
        ],
    )
    upsert_called = False

    def record_upsert(*args, **kwargs):
        nonlocal upsert_called
        upsert_called = True
        return 1

    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_upsert", record_upsert)

    with pytest.raises(ValidationError):
        ingest.ingest_daily("X", "2024-01-01", "2024-01-01")

    assert upsert_called is False


def test_real_valid_bar_dto_flows_through_ingest(
    ohlc_db,
    monkeypatch,
):
    bar = BarDTO(
        code="X",
        dt=datetime(2024, 1, 1),
        open=10,
        high=12,
        low=9,
        close=11,
        volume=100,
        amount=1_000,
    )
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: [bar],
    )
    captured: list[dict] = []

    def capture_upsert(session, model, rows, index_elements, update_cols):
        captured.extend(rows)
        return len(rows)

    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_upsert", capture_upsert)
    monkeypatch.setattr(
        ingest,
        "_dataset_actual_range",
        lambda *args, **kwargs: {
            "start": "2024-01-01",
            "end": "2024-01-01",
            "fetchedAtFloor": "2024-01-01T00:00:00+00:00",
            "fetchedAtWatermark": "2024-01-01T00:00:00+00:00",
        },
    )

    assert ingest.ingest_daily("X", "2024-01-01", "2024-01-01") == 1
    assert captured[0]["open"] == Decimal("10.0")
    assert captured[0]["close"] == Decimal("11.0")


def test_decimal_validation_rejects_large_order_violation_hidden_by_float_rounding():
    with pytest.raises(InvalidOHLCError, match="invalid_ohlc_order"):
        validate_ohlc(
            open_value="1000000000000000000000000000000.1",
            high_value="1000000000000000000000000000000.4",
            low_value=Decimal("1000000000000000000000000000000.2"),
            close_value=Decimal("1000000000000000000000000000000.3"),
            code="X",
            bar_time=datetime(2024, 1, 1),
        )


def test_decimal_validation_preserves_large_exact_values_until_consumption():
    open_value = Decimal("1000000000000000000000000000000.1")
    checked = validate_ohlc(
        open_value=open_value,
        high_value="1000000000000000000000000000000.4",
        low_value="1000000000000000000000000000000.0",
        close_value="1000000000000000000000000000000.3",
        volume="1000000000000000000000000000000",
        amount=Decimal("1000000000000000000000000000000.5"),
        code="X",
        bar_time=datetime(2024, 1, 1),
    )

    assert checked.open is open_value
    assert isinstance(checked.high, Decimal)
    assert checked.high == Decimal("1000000000000000000000000000000.4")
    assert checked.amount == Decimal("1000000000000000000000000000000.5")


@pytest.mark.parametrize("dataset", ["daily", "minute"])
@pytest.mark.parametrize(
    "invalid",
    [
        {"open": None},
        {"close": float("nan")},
        {"high": float("inf")},
        {"open": True},
        {"low": 0},
        {"high": 10, "close": 11},
        {"volume": -1},
        {"amount": -1},
        {"open": "api_key=super-secret"},
    ],
    ids=[
        "missing-open",
        "nan-close",
        "infinite-high",
        "boolean-open",
        "zero-low",
        "invalid-high-low",
        "negative-volume",
        "negative-amount",
        "sensitive-invalid-value",
    ],
)
def test_ingest_rejects_entire_bad_dataset_and_preserves_old_rows(
    ohlc_db,
    monkeypatch,
    dataset,
    invalid,
):
    old_daily = DailyBar(
        code="X",
        trade_date=date(2024, 1, 1),
        open=8,
        high=9,
        low=7,
        close=8.5,
        volume=80,
        amount=680,
    )
    old_minute = MinuteBar(
        code="X",
        dt=datetime(2024, 1, 1, 9, 35),
        period="5",
        open=8,
        high=9,
        low=7,
        close=8.5,
        volume=80,
        amount=680,
    )
    with ohlc_db.begin() as session:
        session.add(old_daily if dataset == "daily" else old_minute)

    good = _provider_bar(dt=datetime(2024, 1, 2, 9, 35))
    bad = _provider_bar(dt=datetime(2024, 1, 1, 9, 35), **invalid)
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: [good, bad],
        get_minute_bars=lambda *args, **kwargs: [good, bad],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "_upsert", _fake_upsert)

    caught = None
    try:
        if dataset == "daily":
            ingest.ingest_daily("X", "2024-01-01", "2024-01-02")
        else:
            ingest.ingest_minute("X", "5", "2024-01-01", "2024-01-02")
    except ValueError as exc:
        caught = exc

    model = DailyBar if dataset == "daily" else MinuteBar
    with ohlc_db() as session:
        rows = list(session.execute(select(model)).scalars().all())
        old = rows[0]

    assert caught is not None
    message = str(caught)
    assert "code=X" in message
    assert "time=2024-01-01" in message
    assert "reason=" in message
    assert "super-secret" not in message
    assert len(rows) == 1, "混合好坏 bars 不得写入好 bar"
    assert float(old.open) == 8
    assert float(old.high) == 9
    assert float(old.low) == 7
    assert float(old.close) == 8.5
    assert old.volume == 80
    assert float(old.amount) == 680


def test_bad_daily_dataset_marks_backfill_run_partial(ohlc_db, monkeypatch):
    provider = SimpleNamespace(
        name="fake",
        get_daily_bars=lambda *args, **kwargs: [
            _provider_bar(dt=datetime(2024, 1, 1), open=None)
        ],
    )
    monkeypatch.setattr(ingest, "_resolve", lambda *args: provider)
    monkeypatch.setattr(ingest, "ingest_adjust", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_capital_flow", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_financials", lambda *args, **kwargs: 0)
    monkeypatch.setattr(ingest, "ingest_news", lambda *args, **kwargs: 0)

    stats = ingest.backfill_codes(["X"], "2024-01-01", "2024-01-02")

    with ohlc_db() as session:
        run = session.execute(select(IngestionRun)).scalar_one()
    datasets = json.loads(run.datasets_json)
    assert run.status == "partial"
    assert stats["runs"][0]["status"] == "partial"
    assert datasets["daily"]["success"] is False
    assert "code=X" in datasets["daily"]["error"]
    assert "time=2024-01-01" in datasets["daily"]["error"]
    assert "reason=" in datasets["daily"]["error"]


def test_daily_loader_rejects_any_invalid_legacy_bar(ohlc_db):
    with ohlc_db.begin() as session:
        session.add_all(
            [
                DailyBar(
                    code="X",
                    trade_date=date(2024, 1, 1),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                    amount=1_000,
                ),
                DailyBar(
                    code="X",
                    trade_date=date(2024, 1, 2),
                    open=10,
                    high=12,
                    low=11,
                    close=10.5,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )

    bars, quality = data_module.load_hfq_bars("X", "2024-01-01", "2024-01-02")

    assert bars == []
    assert quality == "invalid_ohlc"


def test_minute_loader_rejects_invalid_legacy_bar(ohlc_db):
    with ohlc_db.begin() as session:
        session.add_all(
            [
                DailyBar(code="X", trade_date=date(2024, 1, 1), close=9.5),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                    amount=1_000,
                ),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 40),
                    period="5",
                    open=10.5,
                    high=11,
                    low=10,
                    close=0,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )

    bars, quality = data_module.load_minute_bars(
        "X",
        "5m",
        "2024-01-02",
        "2024-01-02",
    )

    assert bars == []
    assert quality == "invalid_ohlc"


def test_minute_loader_marks_missing_when_no_valid_previous_close(ohlc_db):
    with ohlc_db.begin() as session:
        session.add_all(
            [
                DailyBar(code="X", trade_date=date(2024, 1, 1), close=0),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )

    bars, quality = data_module.load_minute_bars(
        "X",
        "5m",
        "2024-01-02",
        "2024-01-02",
    )

    assert bars
    assert quality == "missing_previous_close"


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["X"],
        start="2024-01-01",
        end="2024-01-02",
    )


def test_single_backtest_rejects_invalid_ohlc(monkeypatch):
    monkeypatch.setattr(runner, "load_bars", lambda config: ({}, {"X": "invalid_ohlc"}))

    result = runner.run_backtest(_config())

    assert result["dataQuality"] == {"X": "invalid_ohlc"}
    assert "OHLC" in result["error"]
    assert "X" in result["error"]


def test_grid_backtest_rejects_invalid_ohlc(monkeypatch):
    code = "600000.SH"
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda config: ({}, {code: "invalid_ohlc"}),
    )
    config = _config()
    config.codes = [code]

    result = backtest_run.grid_search(config, {"fast": [2]}, "sharpeRatio")

    assert result["results"] == []
    assert result["dataQuality"] == {code: "invalid_ohlc"}
    assert "OHLC" in result["error"]
    assert code in result["error"]


def test_quote_missing_values_remain_none():
    quote = QuoteDTO(code="X", name="missing")

    result = market._quote_to_stock(quote)

    for field in ("price", "change", "changePercent", "volume", "amount"):
        assert result[field] is None


def test_kline_filters_invalid_legacy_bars_and_reports_quality(
    ohlc_db,
    caplog,
):
    with ohlc_db.begin() as session:
        session.add_all(
            [
                DailyBar(
                    code="600000.SH",
                    trade_date=date(2024, 1, 1),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=0,
                    amount=0,
                ),
                DailyBar(
                    code="600000.SH",
                    trade_date=date(2024, 1, 2),
                    open=10,
                    high=11,
                    low=9,
                    close=None,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )

    result = market.get_kline("600000.SH", "day", 100)
    if isinstance(result, list):
        bars, quality = result, None
    else:
        bars, quality = result["bars"], result["dataQuality"]

    assert quality == "invalid_ohlc"
    assert bars == [
        {
            "time": "2024-01-01",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 0.0,
        }
    ]
    assert "600000.SH" in caplog.text
    assert "2024-01-02" in caplog.text
    assert "reason=" in caplog.text


@pytest.mark.parametrize("period", ["day", "5min"])
def test_kline_overfetches_until_count_valid_bars_or_history_exhausted(
    ohlc_db,
    period,
):
    code = "600000.SH"
    with ohlc_db.begin() as session:
        if period == "day":
            session.add_all(
                [
                    DailyBar(
                        code=code,
                        trade_date=date(2024, 1, day),
                        open=10 + day,
                        high=11 + day,
                        low=9 + day,
                        close=10.5 + day,
                        volume=100,
                        amount=1_000,
                    )
                    for day in (1, 2)
                ]
                + [
                    DailyBar(
                        code=code,
                        trade_date=date(2024, 1, 3),
                        open=13,
                        high=14,
                        low=12,
                        close=None,
                        volume=100,
                        amount=1_000,
                    )
                ]
            )
        else:
            session.add_all(
                [
                    MinuteBar(
                        code=code,
                        dt=datetime(2024, 1, 1, 9, 30 + minute),
                        period="5",
                        open=10 + minute,
                        high=11 + minute,
                        low=9 + minute,
                        close=10.5 + minute,
                        volume=100,
                        amount=1_000,
                    )
                    for minute in (5, 10)
                ]
                + [
                    MinuteBar(
                        code=code,
                        dt=datetime(2024, 1, 1, 9, 45),
                        period="5",
                        open=13,
                        high=14,
                        low=12,
                        close=None,
                        volume=100,
                        amount=1_000,
                    )
                ]
            )

    result = market.get_kline(code, period, count=2)

    assert len(result["bars"]) == 2
    assert result["dataQuality"] == "invalid_ohlc"
    if period == "day":
        assert [bar["time"] for bar in result["bars"]] == [
            "2024-01-01",
            "2024-01-02",
        ]
    else:
        assert [bar["time"] for bar in result["bars"]] == [
            "2024-01-01T09:35:00",
            "2024-01-01T09:40:00",
        ]


def _screen_quote(code: str, **overrides) -> QuoteDTO:
    values = {
        "code": code,
        "name": code,
        "price": 10,
        "change": 1,
        "change_percent": 1,
        "volume": 100,
        "amount": 1_000,
    }
    values.update(overrides)
    return QuoteDTO(**values)


def test_screen_bound_excludes_none_nan_and_inf_values(monkeypatch):
    quotes = [
        _screen_quote("finite"),
        _screen_quote("none", price=None),
        _screen_quote("nan", price=float("nan")),
        _screen_quote("inf", price=float("inf")),
    ]
    monkeypatch.setattr(market, "_ensure_stocks", lambda: quotes)
    monkeypatch.setattr(
        market.quote_cache.cache,
        "get_stocks_snapshot",
        lambda: (quotes, None),
    )

    result = market.screen_stocks(
        {"priceMin": 1},
        sort_by="price",
        sort_order="desc",
    )

    assert result["total"] == 1
    assert [stock["code"] for stock in result["stocks"]] == ["finite"]


@pytest.mark.parametrize(
    ("sort_by", "field"),
    [
        ("price", "price"),
        ("changePercent", "change_percent"),
        ("volume", "volume"),
        ("amount", "amount"),
    ],
)
def test_screen_sort_excludes_non_finite_or_missing_sort_values(
    monkeypatch,
    sort_by,
    field,
):
    quotes = [
        _screen_quote("finite"),
        _screen_quote("none", **{field: None}),
        _screen_quote("nan", **{field: float("nan")}),
        _screen_quote("inf", **{field: float("inf")}),
    ]
    monkeypatch.setattr(market, "_ensure_stocks", lambda: quotes)
    monkeypatch.setattr(
        market.quote_cache.cache,
        "get_stocks_snapshot",
        lambda: (quotes, None),
    )

    result = market.screen_stocks({}, sort_by=sort_by, sort_order="desc")

    assert result["total"] == 1
    assert [stock["code"] for stock in result["stocks"]] == ["finite"]


def test_kline_api_keeps_quality_inside_business_payload(monkeypatch):
    bars = [
        {
            "time": "2024-01-01",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 0.0,
        }
    ]
    monkeypatch.setattr(
        market_api.market,
        "get_kline",
        lambda *args: {"bars": bars, "dataQuality": "invalid_ohlc"},
    )

    response = market_api.kline("X")

    assert response["data"] == {
        "bars": bars,
        "dataQuality": "invalid_ohlc",
    }
    assert "dataQuality" not in {key for key in response if key != "data"}
