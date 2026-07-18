"""Backtrader 真实适配、A 股约束与 native 对拍。"""

from __future__ import annotations

import builtins
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.backtest import runner
from app.backtest.base import BacktestConfig, Strategy
from app.backtest.data import Bar
from app.backtest.engines.backtrader_engine import BacktraderEngine
from app.backtest.engines.native import NativeEngine
from app.backtest.metrics import compute_metrics
from app.backtest.registry import available_engines
from app.backtest.strategies import get_strategy
from app.core.json_payload import load_envelope
from app.schemas.backtest import GridSearchRequest, RunBacktestRequest
from app.services import backtest_run


def _cfg(**overrides) -> BacktestConfig:
    values = {
        "strategy_type": "controlled",
        "params": {},
        "codes": ["X"],
        "start": "2024-01-01",
        "end": "2024-01-10",
        "initial_capital": 100_000.0,
        "slippage": 0.0,
        "engine": "backtrader",
    }
    values.update(overrides)
    return BacktestConfig(**values)


def _bar(
    when: date | datetime,
    open_: float,
    close: float,
    *,
    code: str = "X",
    previous_close: float | None = None,
    limit_ratio: float | None = None,
) -> Bar:
    return Bar(
        code=code,
        date=when,
        open=open_,
        high=max(open_, close) * 1.05,
        low=min(open_, close) * 0.95,
        close=close,
        volume=100_000,
        amount=open_ * 100_000,
        previous_close=previous_close,
        limit_ratio=limit_ratio,
    )


class _BuyOnce(Strategy):
    def initialize(self, ctx) -> None:
        self.sent = False

    def handle_bar(self, ctx, bars) -> None:
        if not self.sent and "X" in bars:
            ctx.order_shares("X", 155)
            self.sent = True


class _EnterThenExit(Strategy):
    def initialize(self, ctx) -> None:
        self.entered = False

    def handle_bar(self, ctx, bars) -> None:
        if "X" not in bars:
            return
        if not self.entered:
            ctx.order_shares("X", 1_000)
            self.entered = True
        elif ctx.portfolio["positions"].get("X", 0):
            ctx.order_target_percent("X", 0)


class _SparseUniverseStrategy(Strategy):
    def initialize(self, ctx) -> None:
        self.seen_universes: list[tuple[str, ...]] = []
        self.sent: set[str] = set()

    def handle_bar(self, ctx, bars) -> None:
        self.seen_universes.append(ctx.universe)
        for code in bars:
            if code not in self.sent:
                ctx.order_shares(code, 100)
                self.sent.add(code)


def test_registry_exposes_real_backtrader_name():
    assert available_engines() == ["native", "backtrader"]


def test_api_schemas_accept_both_engines_and_reject_unknown():
    common = {
        "strategyType": "dual_ma",
        "codes": ["600000.SH"],
        "start": "2024-01-01",
        "end": "2024-01-10",
        "engine": "backtrader",
    }

    assert RunBacktestRequest(**common).engine == "backtrader"
    assert GridSearchRequest(**common, paramGrid={"fast": [3]}).engine == "backtrader"
    with pytest.raises(ValidationError):
        RunBacktestRequest(**{**common, "engine": "unknown"})


def test_grid_api_passes_selected_engine(monkeypatch):
    from app.api.v1 import backtest as backtest_api

    captured = {}
    monkeypatch.setattr(backtest_api.rate_limit, "ai_cost_gate", lambda user_id, kind: None)

    def fake_grid_search(config, param_grid, sort_by):
        captured["engine"] = config.engine
        return {"results": [], "best": None}

    monkeypatch.setattr(backtest_api.backtest_run, "grid_search", fake_grid_search)
    request = GridSearchRequest(
        strategyType="dual_ma",
        paramGrid={"fast": [3]},
        codes=["600000.SH"],
        start="2024-01-01",
        end="2024-01-10",
        engine="backtrader",
    )

    backtest_api.grid(request, SimpleNamespace(id="user-a"))

    assert captured["engine"] == "backtrader"


def test_saved_history_config_keeps_selected_engine(monkeypatch):
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
            "engine": "backtrader",
        },
    )
    request = SimpleNamespace(
        strategyType="dual_ma",
        params={},
        codes=["600000.SH"],
        start="2024-01-01",
        end="2024-01-10",
        initialCapital=100_000,
        slippage=0,
        engine="backtrader",
        frequency="1d",
    )

    result = backtest_run.run_and_save("user-a", request)

    assert load_envelope(captured["row"].config_json)["engine"] == "backtrader"
    assert result["config"]["engine"] == "backtrader"


def test_missing_dependency_has_actionable_error(monkeypatch):
    real_import = builtins.__import__

    def missing_backtrader(name, *args, **kwargs):
        if name == "backtrader":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_backtrader)
    engine = BacktraderEngine()

    with pytest.raises(RuntimeError, match=r"pip install backtrader"):
        engine.run(_cfg(), _BuyOnce(), {"X": [_bar(date(2024, 1, 1), 10, 10)]})


def test_daily_feed_runs_in_cerebro_and_fills_next_open(monkeypatch):
    bars = [
        _bar(date(2024, 1, 1), 10.0, 10.0),
        _bar(date(2024, 1, 2), 10.5, 10.4),
        _bar(date(2024, 1, 3), 10.6, 10.6),
    ]

    def native_must_not_run(*args, **kwargs):
        raise AssertionError("BacktraderEngine 不得委托 NativeEngine")

    monkeypatch.setattr(NativeEngine, "run", native_must_not_run)
    result = BacktraderEngine().run(_cfg(), _BuyOnce(), {"X": bars})

    assert [(fill.side, fill.date, fill.qty, fill.price) for fill in result.fills] == [
        ("buy", date(2024, 1, 2), 100, 10.5)
    ]
    assert len(result.equity_curve) == len(bars)
    assert set(result.equity_curve[-1]) >= {"date", "equity", "cash", "marketValue"}
    assert result.data_quality == {"X": "provided"}


def test_builtin_dual_ma_runs_through_wrapped_context():
    start = date(2024, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), 10 + index * 0.2, 10 + index * 0.2)
        for index in range(8)
    ]

    result = BacktraderEngine().run(
        _cfg(strategy_type="dual_ma", params={"fast": 2, "slow": 3}),
        get_strategy("dual_ma"),
        {"X": bars},
    )

    assert len(result.equity_curve) == len(bars)
    assert result.fills[0].side == "buy"
    assert result.fills[0].date == date(2024, 1, 4)


def test_commission_stamp_tax_and_round_lot_match_trading_rules():
    bars = [
        _bar(date(2024, 1, 1), 10, 10),
        _bar(date(2024, 1, 2), 10, 10),
        _bar(date(2024, 1, 3), 10, 10),
    ]

    result = BacktraderEngine().run(_cfg(), _EnterThenExit(), {"X": bars})

    assert [(fill.side, fill.qty, fill.fee, fill.tax) for fill in result.fills] == [
        ("buy", 1_000, 5.0, 0.0),
        ("sell", 1_000, 5.0, 5.0),
    ]
    assert result.equity_curve[-1]["equity"] == 99_985.0


def test_slippage_is_applied_to_next_open():
    bars = [
        _bar(date(2024, 1, 1), 10, 10),
        _bar(date(2024, 1, 2), 10, 10),
    ]

    result = BacktraderEngine().run(_cfg(slippage=0.01), _BuyOnce(), {"X": bars})

    assert result.fills[0].price == 10.1


def test_limit_up_blocks_buy_without_later_ghost_fill():
    bars = [
        _bar(date(2024, 1, 1), 10, 10, limit_ratio=0.10),
        _bar(date(2024, 1, 2), 11, 11, limit_ratio=0.10),
        _bar(date(2024, 1, 3), 10.5, 10.5, limit_ratio=0.10),
    ]

    result = BacktraderEngine().run(_cfg(), _BuyOnce(), {"X": bars})

    assert result.fills == []


def test_none_limit_ratio_means_no_limit_and_never_falls_back():
    bars = [
        _bar(date(2024, 1, 2), 10, 10, limit_ratio=None),
        _bar(date(2024, 1, 3), 12, 12, limit_ratio=None),
    ]

    result = BacktraderEngine().run(_cfg(), _BuyOnce(), {"X": bars})

    assert len(result.fills) == 1
    assert result.fills[0].price == 12


def test_st_five_percent_limit_ratio_blocks_buy():
    bars = [
        _bar(date(2024, 1, 1), 10, 10, previous_close=9.8, limit_ratio=0.05),
        _bar(date(2024, 1, 2), 10.5, 10.5, limit_ratio=0.05),
    ]

    result = BacktraderEngine().run(_cfg(), _BuyOnce(), {"X": bars})

    assert result.fills == []


def test_minute_t1_blocks_same_day_sell_and_unlocks_next_day():
    bars = [
        _bar(datetime(2024, 1, 2, 9, 35), 10.0, 10.0),
        _bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1),
        _bar(datetime(2024, 1, 2, 9, 45), 10.2, 10.2),
        _bar(datetime(2024, 1, 3, 9, 35), 10.3, 10.3),
    ]

    result = BacktraderEngine().run(
        _cfg(frequency="5m"),
        _EnterThenExit(),
        {"X": bars},
    )

    assert [(fill.side, fill.date) for fill in result.fills] == [
        ("buy", datetime(2024, 1, 2, 9, 40)),
        ("sell", datetime(2024, 1, 3, 9, 35)),
    ]
    assert [point["date"] for point in result.equity_curve] == [
        bar.date.isoformat() for bar in bars
    ]


def test_sparse_multisymbol_feed_keeps_configured_universe_and_symbol_clock():
    strategy = _SparseUniverseStrategy()
    bars = {
        "X": [
            _bar(datetime(2024, 1, 2, 9, 35), 10, 10, code="X"),
            _bar(datetime(2024, 1, 2, 9, 40), 10.1, 10.1, code="X"),
        ],
        "Y": [
            _bar(datetime(2024, 1, 2, 9, 36), 20, 20, code="Y"),
            _bar(datetime(2024, 1, 2, 9, 41), 20.1, 20.1, code="Y"),
        ],
    }

    result = BacktraderEngine().run(
        _cfg(codes=["X", "Y"], frequency="5m"),
        strategy,
        bars,
    )

    assert strategy.seen_universes
    assert set(strategy.seen_universes) == {("X", "Y")}
    assert [(fill.code, fill.date) for fill in result.fills] == [
        ("X", datetime(2024, 1, 2, 9, 40)),
        ("Y", datetime(2024, 1, 2, 9, 41)),
    ]


def test_native_and_backtrader_match_controlled_round_trip():
    start = date(2024, 1, 1)
    prices = [(10.0, 10.0), (10.2, 10.1), (10.4, 10.5), (10.3, 10.2), (10.1, 10.0)]
    bars = [_bar(start + timedelta(days=i), open_, close) for i, (open_, close) in enumerate(prices)]
    native = NativeEngine().run(_cfg(engine="native"), _EnterThenExit(), {"X": bars})
    backtrader = BacktraderEngine().run(_cfg(), _EnterThenExit(), {"X": bars})

    assert len(backtrader.fills) == len(native.fills)
    for actual, expected in zip(backtrader.fills, native.fills, strict=True):
        assert (actual.code, actual.side, actual.date, actual.qty) == (
            expected.code,
            expected.side,
            expected.date,
            expected.qty,
        )
        for field in ("price", "amount", "fee", "tax"):
            assert getattr(actual, field) == pytest.approx(
                getattr(expected, field),
                rel=0,
                abs=0.01,
            )
    assert backtrader.equity_curve[-1]["equity"] == pytest.approx(
        native.equity_curve[-1]["equity"],
        rel=0,
        abs=0.01,
    )

    native_metrics = compute_metrics(native.equity_curve, native.fills, 100_000)["metrics"]
    backtrader_metrics = compute_metrics(
        backtrader.equity_curve,
        backtrader.fills,
        100_000,
    )["metrics"]
    for key in ("totalReturnPercent", "maxDrawdownPercent"):
        assert backtrader_metrics[key] == pytest.approx(
            native_metrics[key],
            rel=0,
            abs=0.01,
        )


def test_runner_returns_friendly_missing_dependency_error(monkeypatch):
    class MissingEngine:
        name = "backtrader"

        def run(self, config, strategy, bars_by_code):
            raise RuntimeError("backtrader 未安装：请运行 `pip install backtrader`")

    monkeypatch.setattr(runner, "get_engine", lambda name: MissingEngine())
    monkeypatch.setattr(runner, "get_strategy", lambda name: _BuyOnce())
    bars = {"X": [_bar(date(2024, 1, 1), 10, 10), _bar(date(2024, 1, 2), 10, 10)]}

    result = runner.run_on_bars(
        _cfg(),
        bars,
        {"X": "full"},
        benchmark_bars=[],
        benchmark_quality="full",
    )

    assert result["engine"] == "backtrader"
    assert result["dataQuality"] == {
        "X": "full",
        "000300.SH:benchmark": "full",
    }
    assert "pip install backtrader" in result["error"]
