"""内置策略注册表。

新增策略：实现 ``base.Strategy`` 子类（``initialize`` + ``handle_bar``）并在此登记一行——
注册表自动接入引擎与（后续）前端参数表单。共创贡献门槛即此。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.strategies.boll import Boll
from app.backtest.strategies.composite_mf import CompositeMultiFactor
from app.backtest.strategies.donchian_breakout import DonchianBreakout
from app.backtest.strategies.dual_ma import DualMA
from app.backtest.strategies.momentum import Momentum
from app.backtest.strategies.rsi import RSI
from app.backtest.strategies.xs_momentum import CrossSectionalMomentum
from app.backtest.strategies.zscore_reversion import ZScoreReversion

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "dual_ma": DualMA,
    "rsi": RSI,
    "boll": Boll,
    "momentum": Momentum,
    "donchian_breakout": DonchianBreakout,
    "xs_momentum": CrossSectionalMomentum,
    "zscore_reversion": ZScoreReversion,
    "composite_mf": CompositeMultiFactor,
}


def get_strategy(strategy_type: str) -> Strategy:
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if cls is None:
        raise ValueError(f"未知策略: {strategy_type}（可选: {', '.join(STRATEGY_REGISTRY)}）")
    return cls()


def available_strategies() -> list[str]:
    return list(STRATEGY_REGISTRY)
