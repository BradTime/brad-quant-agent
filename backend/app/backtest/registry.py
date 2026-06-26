"""回测引擎注册表 + 选择器（呼应 providers.registry 的可热插拔风格）。

``native`` 默认实现；``backtrader`` 惰性加载（预留适配器，未安装/未实现时友好报错）。
"""

from __future__ import annotations

from app.backtest.base import BacktestEngine
from app.backtest.engines.native import NativeEngine

ENGINE_REGISTRY: dict[str, type[BacktestEngine]] = {
    "native": NativeEngine,
}


def get_engine(name: str = "native") -> BacktestEngine:
    name = (name or "native").lower()
    if name == "backtrader":
        # 预留引擎：惰性导入，避免未安装 backtrader 时影响默认路径
        from app.backtest.engines.backtrader_engine import BacktraderEngine

        return BacktraderEngine()
    cls = ENGINE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"未知回测引擎: {name}（可选: {', '.join(ENGINE_REGISTRY)} 或 backtrader[预留]）"
        )
    return cls()


def available_engines() -> list[str]:
    return [*ENGINE_REGISTRY.keys(), "backtrader(预留)"]
