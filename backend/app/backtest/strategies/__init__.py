"""内置策略注册表。

新增策略：实现 ``base.Strategy`` 子类（``initialize`` + ``handle_bar``）并在此登记一行——
注册表自动接入引擎与（后续）前端参数表单。共创贡献门槛即此。
"""

from __future__ import annotations

from app.backtest.base import Strategy
from app.backtest.strategies.dual_ma import DualMA

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "dual_ma": DualMA,
}


def get_strategy(strategy_type: str) -> Strategy:
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if cls is None:
        raise ValueError(f"未知策略: {strategy_type}（可选: {', '.join(STRATEGY_REGISTRY)}）")
    return cls()


def available_strategies() -> list[str]:
    return list(STRATEGY_REGISTRY)
