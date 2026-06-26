"""backtrader 引擎适配器（**预留方案**）。

保留 backtrader 作为可选「高级引擎」：未来需要更丰富的 order 类型 / 指标库 / 分钟级 /
社区生态时接入，**不改动策略层与 API**；并可与自研 native 引擎交叉验证（对拍）。

当前为骨架：惰性检测依赖 + ``run()`` 未实现。接入步骤（TODO）：
  1. 惰性 import backtrader（未安装则提示 `pip install backtrader`，不入 requirements 以免重依赖）。
  2. cerebro 装配：``bt.Cerebro()``；把内置 Strategy 包装为 ``bt.Strategy``；
     用 ``bt.feeds.PandasData`` 馈送 ``data.load_hfq_bars`` 的后复权 OHLC。
  3. A 股费用：自定义 ``bt.CommissionInfo``（佣金万2.5/最低5 + 卖出印花税千1，见 trading_rules）。
  4. T+1：自定义 Sizer / 在 strategy.next() 内约束「当日买入次日可卖」。
  5. 涨跌停：next() 内按 ``trading_rules.price_limit_ratio`` 限制可成交方向。
  6. 结果映射：运行 analyzer（TimeReturn / DrawDown / TradeAnalyzer）→ 映射到 EngineResult。
"""

from __future__ import annotations

from app.backtest.base import BacktestConfig, BacktestEngine, EngineResult, Strategy
from app.backtest.data import Bar


class BacktraderEngine(BacktestEngine):
    name = "backtrader"

    def __init__(self) -> None:
        try:
            import backtrader  # noqa: F401

            self._available = True
        except ImportError:
            self._available = False

    def run(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        bars_by_code: dict[str, list[Bar]],
    ) -> EngineResult:
        if not self._available:
            raise RuntimeError(
                "backtrader 引擎为预留方案且依赖未安装：请先 `pip install backtrader`，"
                "并完成适配（见本文件 TODO 与 docs/phase4-backtest-design.md §2）"
            )
        raise NotImplementedError(
            "backtrader 适配器为预留方案，run() 待实现（cerebro 装配 / A股费用 / T+1 / 结果映射）"
        )
