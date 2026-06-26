"""回测引擎抽象与通用数据结构。

引擎可插拔：``native``（自研，默认）与 ``backtrader``（预留）共同实现 ``BacktestEngine``，
上层 API/策略层不感知具体引擎，经 ``BacktestConfig.engine`` 选择（呼应 DataProvider 风格）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from app.backtest.data import Bar
from app.services import trading_rules


@dataclass
class BacktestConfig:
    """回测配置（对齐前端 BacktestConfig + A 股扩展）。"""

    strategy_type: str
    params: dict
    codes: list[str]
    start: str
    end: str
    initial_capital: float = trading_rules.INITIAL_CASH
    slippage: float = 0.0
    benchmark: str = "000300.SH"
    engine: str = "native"


@dataclass
class Fill:
    """单笔成交。"""

    code: str
    date: date
    side: str  # buy / sell
    price: float
    qty: int
    amount: float
    fee: float
    tax: float


@dataclass
class EngineResult:
    """引擎原始产出：权益曲线 + 成交流水 + 数据质量。绩效指标在 metrics 层（M2+）计算。"""

    equity_curve: list[dict]  # [{date, equity, cash, marketValue}]
    fills: list[Fill]
    data_quality: dict = field(default_factory=dict)  # {code: coverage}


class Strategy(ABC):
    """策略基类（聚宽 / RQAlpha 风格）：initialize 设置，handle_bar 每交易日出信号。"""

    @abstractmethod
    def initialize(self, ctx) -> None: ...

    @abstractmethod
    def handle_bar(self, ctx, bars: dict[str, Bar]) -> None: ...


class BacktestEngine(ABC):
    """回测引擎抽象接口。具体实现：NativeEngine（默认）/ BacktraderEngine（预留）。"""

    name: str = "base"

    @abstractmethod
    def run(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        bars_by_code: dict[str, list[Bar]],
    ) -> EngineResult: ...
