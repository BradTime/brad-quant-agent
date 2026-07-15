"""自研事件驱动引擎（native，默认实现）。

事件循环（逐 bar）：
  跨自然交易日时 settle_t1 → execute_open（上一根 bar 意图按当前开盘成交）
  → handle_bar（仅用 ≤当前 bar 数据出意图）→ mark_to_market（按当前收盘记权益）。

PIT：``ctx.history`` 只给截至当前 bar 的数据；信号下一根 bar 开盘成交，杜绝前视偏差。
"""

from __future__ import annotations

import bisect

from app.backtest.base import BacktestConfig, BacktestEngine, EngineResult, Strategy
from app.backtest.broker import Broker
from app.backtest.context import Context
from app.backtest.data import Bar


class NativeEngine(BacktestEngine):
    name = "native"

    def run(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        bars_by_code: dict[str, list[Bar]],
    ) -> EngineResult:
        # 预构建 timestamp->{code:bar} 与 code->有序时间轴（history 二分用）
        day_map: dict = {}
        code_dates: dict[str, list] = {}
        for code, bars in bars_by_code.items():
            code_dates[code] = [b.date for b in bars]
            for b in bars:
                day_map.setdefault(b.date, {})[code] = b
        all_dates = sorted(day_map.keys())

        broker = Broker(config.initial_capital, config.slippage)
        for code, bars in bars_by_code.items():
            if bars and bars[0].previous_close is not None:
                broker.seed_previous_close(code, bars[0].previous_close)

        def history_fn(code: str, field: str, n: int, asof) -> list[float]:
            dates = code_dates.get(code, [])
            i = bisect.bisect_right(dates, asof)  # 截至 asof（含）的根数
            window = bars_by_code[code][:i][-n:]
            return [float(getattr(b, field)) for b in window]

        ctx = Context(broker, config.params, history_fn, universe=config.codes)
        strategy.initialize(ctx)

        equity_curve: list[dict] = []
        for d in all_dates:
            bars_today = day_map[d]
            broker.settle_t1(d)
            broker.execute_open(bars_today, d)
            ctx._set_date(d)
            strategy.handle_bar(ctx, bars_today)
            equity_curve.append(
                {"date": d.isoformat(), "equity": round(broker.mark_to_market(bars_today), 2)}
            )

        return EngineResult(equity_curve=equity_curve, fills=broker.fills, data_quality={})
