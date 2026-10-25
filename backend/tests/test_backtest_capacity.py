from datetime import date

from app.backtest.base import BacktestConfig, Strategy
from app.backtest.broker import Broker
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine


class _FullExposure(Strategy):
    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        for code in bars:
            ctx.order_target_percent(code, 1.0)


def _bar(day: int, *, volume: int | None, price: float = 10.0) -> Bar:
    return Bar(
        code="X",
        date=date(2024, 1, day),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=price * volume if volume is not None else None,
    )


def _config(**overrides) -> BacktestConfig:
    values = {
        "strategy_type": "dual_ma",
        "params": {},
        "codes": ["X"],
        "start": "2024-01-01",
        "end": "2024-01-03",
        "initial_capital": 2_000_000.0,
        "slippage": 0.0,
        "max_participation": 0.01,
    }
    values.update(overrides)
    return BacktestConfig(**values)


def test_fill_is_capped_by_signal_day_volume_not_fill_day_volume():
    bars = [
        _bar(1, volume=1_000_000),
        _bar(2, volume=100_000_000),
    ]
    result = NativeEngine().run(_config(), _FullExposure(), {"X": bars})

    assert len(result.fills) == 1
    assert result.fills[0].qty == 10_000
    assert result.execution_quality["volumeCappedFills"] == 1


def test_missing_signal_day_volume_fails_closed():
    bars = [_bar(1, volume=None), _bar(2, volume=100_000_000)]
    result = NativeEngine().run(_config(), _FullExposure(), {"X": bars})
    assert result.fills == []
    assert result.execution_quality["volumeMissingRejections"] == 1


def test_backend_defaults_to_ten_basis_points_and_one_percent_capacity():
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["X"],
        start="2024-01-01",
        end="2024-01-03",
    )
    assert config.slippage == 0.001
    assert config.max_participation == 0.01


def test_slippage_is_clamped_to_legal_daily_price_limit():
    broker = Broker(
        initial_cash=100_000,
        slippage=0.05,
        max_participation=1,
    )
    broker.seed_previous_close("X", 10)
    signal_bar = _bar(1, volume=1_000_000, price=10)
    broker.set_signal_bars({"X": signal_bar})
    broker.submit_shares("X", 100)
    fill_bar = _bar(2, volume=1_000_000, price=10.9)
    fill_bar.limit_ratio = 0.1

    broker.execute_open({"X": fill_bar}, fill_bar.date)

    assert broker.fills[0].price == 11.0
