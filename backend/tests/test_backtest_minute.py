"""分钟级回测：数据、撮合、T+1、涨跌停、API 与持久化。"""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.backtest import data as data_module
from app.backtest import runner
from app.backtest.base import BacktestConfig, Strategy
from app.backtest.broker import Broker, Position
from app.backtest.context import Context
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine
from app.backtest.metrics import compute_metrics
from app.main import app
from app.models.market import AdjustFactor, DailyBar, Instrument, MinuteBar
from app.services import backtest_run, rate_limit


def _cfg(**overrides) -> BacktestConfig:
    values = {
        "strategy_type": "dual_ma",
        "params": {},
        "codes": ["X"],
        "start": "2024-01-01",
        "end": "2024-01-03",
        "initial_capital": 100_000.0,
    }
    values.update(overrides)
    return BacktestConfig(**values)


def _minute_bar(
    dt: datetime,
    open_: float,
    close: float,
    *,
    code: str = "X",
) -> Bar:
    return Bar(
        code=code,
        date=dt,
        open=open_,
        high=max(open_, close),
        low=min(open_, close),
        close=close,
        volume=100_000,
        amount=open_ * 100_000,
    )


@pytest.fixture
def minute_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    MinuteBar.__table__.create(bind=engine)
    AdjustFactor.__table__.create(bind=engine)
    DailyBar.__table__.create(bind=engine)
    Instrument.__table__.create(bind=engine)
    monkeypatch.setattr(data_module, "SessionLocal", test_session)
    try:
        yield test_session
    finally:
        engine.dispose()


def test_backtest_config_frequency_defaults_to_daily():
    assert getattr(_cfg(), "frequency", None) == "1d"


def test_load_minute_bars_sorts_and_applies_factor_by_trade_date(minute_db):
    loader = getattr(data_module, "load_minute_bars", None)
    assert loader is not None, "应提供分钟行情加载器"

    with minute_db() as session:
        session.add_all(
            [
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 3, 9, 40),
                    period="5",
                    open=8.2,
                    high=8.4,
                    low=8.1,
                    close=8.3,
                    volume=200,
                    amount=1_640,
                ),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10,
                    high=10.2,
                    low=9.9,
                    close=10.1,
                    volume=100,
                    amount=1_000,
                ),
                AdjustFactor(code="X", ex_date=date(2024, 1, 2), back_adjust_factor=1),
                AdjustFactor(code="X", ex_date=date(2024, 1, 3), back_adjust_factor=1.5),
            ]
        )
        session.commit()

    bars, coverage = loader("X", "5m", "2024-01-02", "2024-01-03")

    assert coverage == "full"
    assert [bar.date for bar in bars] == [
        datetime(2024, 1, 2, 9, 35),
        datetime(2024, 1, 3, 9, 40),
    ]
    assert bars[0].open == 10
    assert bars[1].open == 12.3
    assert bars[1].close == 12.45


def test_load_minute_bars_seeds_first_day_previous_close(minute_db):
    with minute_db() as session:
        session.add_all(
            [
                DailyBar(code="X", trade_date=date(2024, 1, 1), close=10),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10.5,
                    high=10.6,
                    low=10.4,
                    close=10.5,
                    volume=100,
                    amount=1_050,
                ),
            ]
        )
        session.commit()

    bars, _ = data_module.load_minute_bars("X", "5m", "2023-01-01", "2024-01-02")

    assert bars[0].previous_close == 10


def test_current_st_name_does_not_rewrite_historical_price_limits(minute_db):
    with minute_db() as session:
        session.add_all(
            [
                Instrument(
                    code="X",
                    name="*ST测试",
                    exchange="SH",
                    fetched_at=datetime(2024, 1, 1),
                ),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )
        session.commit()

    bars, _ = data_module.load_minute_bars("X", "5m", "2024-01-02", "2024-01-02")

    assert bars[0].limit_ratio == 0.10


def test_load_minute_bars_does_not_apply_future_st_name_to_history(minute_db):
    with minute_db() as session:
        session.add_all(
            [
                Instrument(
                    code="X",
                    name="*ST测试",
                    exchange="SH",
                    fetched_at=datetime(2024, 1, 3),
                ),
                MinuteBar(
                    code="X",
                    dt=datetime(2024, 1, 2, 9, 35),
                    period="5",
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    volume=100,
                    amount=1_000,
                ),
            ]
        )
        session.commit()

    bars, coverage = data_module.load_minute_bars(
        "X",
        "5m",
        "2024-01-02",
        "2024-01-02",
    )

    assert bars[0].limit_ratio == 0.10
    assert coverage == "none"


def test_runner_dispatches_minute_frequency_without_daily_fetch(monkeypatch):
    calls: list[tuple[str, str]] = []
    expected = _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10)

    def minute_loader(code: str, frequency: str, start: str, end: str):
        calls.append(("minute", frequency))
        return [expected], "full"

    def daily_loader(code: str, start: str, end: str):
        calls.append(("daily", "1d"))
        return [], "none"

    monkeypatch.setattr(runner, "load_minute_bars", minute_loader, raising=False)
    monkeypatch.setattr(runner, "load_hfq_bars", daily_loader)
    config = _cfg()
    config.frequency = "15m"

    bars_by_code, quality = runner.load_bars(config)

    assert calls == [("minute", "15m")]
    assert bars_by_code == {"X": [expected]}
    assert quality == {"X": "full"}


class _AlwaysFull(Strategy):
    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        for code in bars:
            ctx.order_target_percent(code, 1.0)


def test_minute_signal_fills_at_next_bar_open():
    bars = [
        _minute_bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0),
        _minute_bar(datetime(2024, 1, 2, 9, 40), 10.2, 10.1),
        _minute_bar(datetime(2024, 1, 2, 9, 45), 10.3, 10.2),
    ]

    result = NativeEngine().run(_cfg(), _AlwaysFull(), {"X": bars})

    assert result.fills[0].date == datetime(2024, 1, 2, 9, 40)
    assert result.fills[0].price == 10.2


def test_minute_first_day_limit_uses_preloaded_previous_close():
    bars = [
        _minute_bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0),
        _minute_bar(datetime(2024, 1, 2, 9, 40), 11.0, 11.0),
    ]
    bars[0].previous_close = 10.0

    result = NativeEngine().run(_cfg(frequency="5m"), _AlwaysFull(), {"X": bars})

    assert result.fills == []


class _BuyEachSymbolOnce(Strategy):
    def initialize(self, ctx) -> None:
        self.sent: set[str] = set()

    def handle_bar(self, ctx, bars) -> None:
        for code in bars:
            if code not in self.sent:
                ctx.order_shares(code, 100)
                self.sent.add(code)


def test_sparse_multisymbol_orders_wait_for_each_symbols_next_bar():
    bars = {
        "X": [
            _minute_bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0, code="X"),
            _minute_bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1, code="X"),
        ],
        "Y": [
            _minute_bar(datetime(2024, 1, 2, 9, 36), 20.0, 20.0, code="Y"),
            _minute_bar(datetime(2024, 1, 2, 9, 41), 20.1, 20.1, code="Y"),
        ],
    }

    result = NativeEngine().run(
        _cfg(codes=["X", "Y"], frequency="5m"),
        _BuyEachSymbolOnce(),
        bars,
    )

    assert [(fill.code, fill.date) for fill in result.fills] == [
        ("X", datetime(2024, 1, 2, 9, 40)),
        ("Y", datetime(2024, 1, 2, 9, 41)),
    ]


def test_context_exposes_stable_configured_universe():
    ctx = Context(Broker(100_000), {}, lambda *_: [], universe=["X", "Y"])

    assert ctx.universe == ("X", "Y")


def test_sparse_mark_to_market_uses_latest_intraday_price():
    broker = Broker(100_000)
    broker.positions["X"] = Position(qty=100, available=100, avg_cost=9)
    broker.mark_to_market({"X": _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10)})

    equity = broker.mark_to_market(
        {"Y": _minute_bar(datetime(2024, 1, 2, 9, 36), 20, 20, code="Y")}
    )

    assert equity == 101_000


class _BuyThenExit(Strategy):
    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        if ctx.portfolio["positions"].get("X", 0):
            ctx.order_target_percent("X", 0)
        else:
            ctx.order_shares("X", 1_000)


def test_minute_t1_blocks_same_day_sell_and_unlocks_next_natural_day():
    bars = [
        _minute_bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0),
        _minute_bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1),
        _minute_bar(datetime(2024, 1, 2, 9, 45), 10.2, 10.2),
        _minute_bar(datetime(2024, 1, 3, 9, 35), 10.3, 10.3),
    ]

    result = NativeEngine().run(_cfg(), _BuyThenExit(), {"X": bars})

    assert [(fill.side, fill.date) for fill in result.fills] == [
        ("buy", datetime(2024, 1, 2, 9, 40)),
        ("sell", datetime(2024, 1, 3, 9, 35)),
    ]


class _BuyOnSecondDay(Strategy):
    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        now = ctx.current_date
        if now.date() == date(2024, 1, 2) and not ctx.portfolio["positions"]:
            ctx.order_shares("X", 1_000)


def test_minute_price_limit_uses_previous_trading_day_close_not_previous_minute():
    bars = [
        _minute_bar(datetime(2024, 1, 1, 14, 55), 10.0, 10.0),
        _minute_bar(datetime(2024, 1, 2, 9, 35), 9.0, 9.0),
        _minute_bar(datetime(2024, 1, 2, 9, 40), 10.5, 10.5),
    ]

    result = NativeEngine().run(_cfg(), _BuyOnSecondDay(), {"X": bars})

    assert [(fill.side, fill.price) for fill in result.fills] == [("buy", 10.5)]


class _RecordHistory(Strategy):
    def __init__(self) -> None:
        self.windows: list[list[float]] = []

    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        self.windows.append(ctx.history("X", "close", 99))


def test_minute_history_contains_only_bars_through_current_timestamp():
    bars = [
        _minute_bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0),
        _minute_bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1),
        _minute_bar(datetime(2024, 1, 2, 9, 45), 10.2, 10.2),
    ]
    strategy = _RecordHistory()

    NativeEngine().run(_cfg(), strategy, {"X": bars})

    assert strategy.windows == [[10.0], [10.0, 10.1], [10.0, 10.1, 10.2]]


def test_missing_minute_data_returns_explicit_error_and_quality(monkeypatch):
    config = _cfg()
    config.frequency = "5m"
    monkeypatch.setattr(runner, "load_bars", lambda cfg: ({}, {"X": "missing"}))

    result = runner.run_backtest(config)

    assert result["dataQuality"] == {"X": "missing"}
    assert "5m" in result["error"]
    assert "分钟" in result["error"]
    assert "不会自动实时抓取" in result["error"]


def test_minute_backtest_rejects_when_any_requested_symbol_is_missing(monkeypatch):
    config = _cfg(codes=["X", "Y"], frequency="5m")
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda cfg: (
            {"X": [_minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10)]},
            {"X": "full", "Y": "missing"},
        ),
    )

    result = runner.run_backtest(config)

    assert "Y" in result["error"]
    assert result["dataQuality"]["Y"] == "missing"


def test_daily_benchmark_maps_to_every_minute_equity_point():
    computed = {
        "metrics": {"totalReturnPercent": 5.0},
        "equityCurve": [
            {"date": "2024-01-02T09:35:00", "equity": 100_000},
            {"date": "2024-01-02T09:40:00", "equity": 100_100},
            {"date": "2024-01-03T09:35:00", "equity": 105_000},
            {"date": "2024-01-03T15:00:00", "equity": 105_100},
        ],
    }
    benchmark = [
        Bar("000300.SH", date(2024, 1, 1), 9, 9, 9, 9, 1, 9),
        Bar("000300.SH", date(2024, 1, 2), 10, 10, 10, 10, 1, 10),
        Bar("000300.SH", date(2024, 1, 3), 11, 11, 11, 11, 1, 11),
    ]

    runner._attach_benchmark(computed, {}, "2024-01-02", "2024-01-03", benchmark)

    assert [point["benchmark"] for point in computed["equityCurve"]] == [
        0.0,
        11.11,
        11.11,
        22.22,
    ]
    assert computed["metrics"]["benchmarkReturnPercent"] == 22.22


def test_minute_metric_sampling_uses_last_equity_of_each_day():
    curve = [
        {"date": "2024-01-02T09:35:00", "equity": 100_000},
        {"date": "2024-01-02T15:00:00", "equity": 101_000},
        {"date": "2024-01-03T09:35:00", "equity": 100_500},
        {"date": "2024-01-03T15:00:00", "equity": 102_000},
    ]

    sampled = runner._daily_close_equity(curve)

    assert sampled == [
        {"date": "2024-01-02T15:00:00", "equity": 101_000},
        {"date": "2024-01-03T15:00:00", "equity": 102_000},
    ]


def test_minute_risk_metrics_include_first_day_return_from_initial_capital():
    daily_closes = [
        {"date": "2024-01-02T15:00:00", "equity": 110_000},
        {"date": "2024-01-03T15:00:00", "equity": 100_000},
    ]

    metrics = compute_metrics(
        daily_closes,
        [],
        100_000,
        return_curve=daily_closes,
    )["metrics"]

    assert metrics["sharpeRatio"] == pytest.approx(0.5345, abs=0.001)


def test_backtest_discloses_missing_historical_st_status():
    bars = {
        "X": [
            _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10),
            _minute_bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1),
        ]
    }

    result = runner.run_on_bars(
        _cfg(frequency="5m"),
        bars,
        {"X": "full"},
        benchmark_bars=[],
    )

    assert result["ruleQuality"]["historicalST"] == "unavailable"


def test_common_data_range_uses_multisymbol_overlap():
    bars = {
        "X": [
            _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10, code="X"),
            _minute_bar(datetime(2024, 1, 2, 10, 0), 10, 10, code="X"),
        ],
        "Y": [
            _minute_bar(datetime(2024, 1, 2, 9, 40), 20, 20, code="Y"),
            _minute_bar(datetime(2024, 1, 2, 10, 5), 20, 20, code="Y"),
        ],
    }

    assert runner._common_data_range(bars) == (
        datetime(2024, 1, 2, 9, 40),
        datetime(2024, 1, 2, 10, 0),
    )


def test_common_alignment_rejects_symbol_without_bar_inside_overlap():
    bars = {
        "X": [
            _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10, code="X"),
            _minute_bar(datetime(2024, 1, 2, 9, 45), 10, 10, code="X"),
        ],
        "Y": [_minute_bar(datetime(2024, 1, 2, 9, 40), 20, 20, code="Y")],
    }

    aligned, _ = runner._align_bars_to_common_range(bars)

    assert aligned is None


def test_common_alignment_preserves_previous_day_close_seed():
    x_first = _minute_bar(datetime(2024, 1, 2, 9, 35), 10, 10, code="X")
    x_first.previous_close = 9.5
    bars = {
        "X": [
            x_first,
            _minute_bar(datetime(2024, 1, 2, 9, 45), 10.2, 10.2, code="X"),
        ],
        "Y": [
            _minute_bar(datetime(2024, 1, 2, 9, 40), 20, 20, code="Y"),
            _minute_bar(datetime(2024, 1, 2, 9, 50), 20, 20, code="Y"),
        ],
    }

    aligned, _ = runner._align_bars_to_common_range(bars)

    assert aligned is not None
    assert aligned["X"][0].previous_close == 9.5


@pytest.fixture
def backtest_client(monkeypatch):
    identity = {"user_id": "user-a"}

    def current_user():
        if identity["user_id"] is None:
            raise HTTPException(status_code=401, detail="未认证")
        return SimpleNamespace(id=identity["user_id"])

    app.dependency_overrides[get_current_user] = current_user
    monkeypatch.setattr(rate_limit, "ai_cost_gate", lambda user_id, kind: None)
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _run_payload(frequency: str) -> dict:
    return {
        "strategyType": "dual_ma",
        "params": {"fast": 5, "slow": 20},
        "codes": ["X"],
        "start": "2024-01-01",
        "end": "2024-01-03",
        "initialCapital": 100_000,
        "slippage": 0,
        "frequency": frequency,
    }


@pytest.mark.parametrize("path", ["/api/v1/backtest/run", "/api/v1/backtest/grid"])
def test_api_rejects_invalid_frequency_with_400(backtest_client, monkeypatch, path):
    monkeypatch.setattr(
        backtest_run,
        "run_and_save",
        lambda user_id, req: {"status": "completed"},
    )
    monkeypatch.setattr(
        backtest_run,
        "grid_search",
        lambda cfg, grid, sort_by: {"results": []},
    )
    payload = _run_payload("2m")
    if path.endswith("/grid"):
        payload["paramGrid"] = {"fast": [5, 10]}
        payload["sortBy"] = "sharpeRatio"

    response = backtest_client.post(path, json=payload)

    assert response.status_code == 400


def test_api_passes_frequency_to_single_run_and_grid(backtest_client, monkeypatch):
    seen: list[tuple[str, str | None]] = []

    def fake_run(user_id, req):
        seen.append(("run", getattr(req, "frequency", None)))
        return {"status": "completed"}

    def fake_grid(config, grid, sort_by):
        seen.append(("grid", getattr(config, "frequency", None)))
        return {"results": [], "best": None}

    monkeypatch.setattr(backtest_run, "run_and_save", fake_run)
    monkeypatch.setattr(backtest_run, "grid_search", fake_grid)

    run_response = backtest_client.post("/api/v1/backtest/run", json=_run_payload("15m"))
    grid_payload = {
        **_run_payload("30m"),
        "paramGrid": {"fast": [5, 10]},
        "sortBy": "sharpeRatio",
    }
    grid_response = backtest_client.post("/api/v1/backtest/grid", json=grid_payload)

    assert run_response.status_code == grid_response.status_code == 200
    assert seen == [("run", "15m"), ("grid", "30m")]


def test_saved_run_config_keeps_frequency(monkeypatch):
    captured = {}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def add(self, row):
            captured["row"] = row

        def commit(self):
            pass

    monkeypatch.setattr(backtest_run, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        backtest_run,
        "run_backtest",
        lambda config: {
            "metrics": {},
            "equityCurve": [],
            "trades": [],
            "dataQuality": {},
            "engine": "native",
        },
    )
    req = SimpleNamespace(
        strategyType="dual_ma",
        params={},
        codes=["X"],
        start="2024-01-01",
        end="2024-01-03",
        initialCapital=100_000,
        slippage=0,
        engine="native",
        frequency="60m",
    )

    result = backtest_run.run_and_save("user-a", req)

    assert json.loads(captured["row"].config_json)["frequency"] == "60m"
    assert result["config"]["frequency"] == "60m"


def test_review_input_discloses_requested_and_actual_ranges(monkeypatch):
    monkeypatch.setattr(
        backtest_run,
        "get_run",
        lambda user_id, run_id: {
            "config": {
                "strategyType": "dual_ma",
                "params": {},
                "codes": ["X"],
                "frequency": "5m",
                "start": "2023-01-01",
                "end": "2024-01-03",
                "initialCapital": 100_000,
                "slippage": 0,
            },
            "actualRange": {
                "start": "2024-01-02T09:35:00",
                "end": "2024-01-03T15:00:00",
            },
            "metrics": {},
            "trades": [],
        },
    )

    text = backtest_run.build_review_input("user-a", "run-1")

    assert "请求区间 2023-01-01~2024-01-03" in text
    assert "实际区间 2024-01-02T09:35:00~2024-01-03T15:00:00" in text
