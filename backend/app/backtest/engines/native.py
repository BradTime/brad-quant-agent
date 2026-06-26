"""自研事件驱动引擎（native，默认实现）。

M1：结构与接口就绪（骨架）。M2 实现完整事件循环：
  逐 trade_date → settle_t1 → fill_pending_open（涨跌停/整手/费用/滑点，复用 trading_rules）
  → strategy.handle_bar（仅用 ≤当日数据）→ mark_to_market 记权益。
"""

from __future__ import annotations

from app.backtest.base import BacktestConfig, BacktestEngine, EngineResult, Strategy
from app.backtest.data import Bar


class NativeEngine(BacktestEngine):
    name = "native"

    def run(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        bars_by_code: dict[str, list[Bar]],
    ) -> EngineResult:
        # M2：完整事件循环。M1 仅占位，保证引擎可被注册/选择/单测装配。
        raise NotImplementedError("native 事件循环将在 M2 实现（见 docs/phase4-backtest-design.md M2）")
