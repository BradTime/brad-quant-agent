"""回测引擎注册表 + 选择器（呼应 providers.registry 的可热插拔风格）。"""

from __future__ import annotations

from app.backtest.base import BacktestEngine
from app.backtest.engines.backtrader_engine import BacktraderEngine
from app.backtest.engines.native import NativeEngine

ENGINE_REGISTRY: dict[str, type[BacktestEngine]] = {
    "native": NativeEngine,
    "backtrader": BacktraderEngine,
}


def get_engine(name: str = "native") -> BacktestEngine:
    name = (name or "native").lower()
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"未知回测引擎: {name}（可选: {', '.join(ENGINE_REGISTRY)}）")
    return cls()


def available_engines() -> list[str]:
    return list(ENGINE_REGISTRY)
