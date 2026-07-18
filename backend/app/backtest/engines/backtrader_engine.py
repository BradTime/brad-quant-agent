"""Backtrader Cerebro 适配器。

Backtrader 负责 PandasData 装载、多数据时间轴同步和 ``bt.Strategy`` 生命周期；现有
``Strategy`` 经包装后继续使用 ``Context.history/order_*``。A 股撮合约束由适配器内的
共享 ``Broker`` 显式执行，因为 Backtrader 默认 broker 无法同时精确表达最低佣金、卖出
印花税、自然日 T+1 和按昨收判断的涨跌停。该执行层不是 NativeEngine 委托：
事件循环由 Cerebro 驱动，且没有调用 ``NativeEngine.run``。

信号在 Cerebro 当前 bar 的 ``next`` 中产生，留在共享撮合账本，至该标的下一根 bar
开盘执行；这与 native 的下一 bar 开盘口径一致。输入 bars 已由 data 层完成后复权。
"""

from __future__ import annotations

import bisect

import pandas as pd

from app.backtest.base import BacktestConfig, BacktestEngine, EngineResult, Strategy
from app.backtest.broker import Broker
from app.backtest.context import Context
from app.backtest.data import Bar


class BacktraderEngine(BacktestEngine):
    name = "backtrader"

    def __init__(self) -> None:
        try:
            import backtrader as bt
        except ImportError as exc:
            self._bt = None
            self._import_error = exc
        else:
            self._bt = bt
            self._import_error = None

    def run(
        self,
        config: BacktestConfig,
        strategy: Strategy,
        bars_by_code: dict[str, list[Bar]],
    ) -> EngineResult:
        if self._bt is None:
            raise RuntimeError(
                "backtrader 引擎依赖未安装：请运行 `pip install backtrader` 后重试"
            ) from self._import_error

        bt = self._bt
        ordered_bars = {
            code: sorted(bars_by_code.get(code, []), key=lambda bar: bar.date)
            for code in config.codes
            if bars_by_code.get(code)
        }
        if not ordered_bars:
            return EngineResult(equity_curve=[], fills=[], data_quality={})

        code_dates = {
            code: [bar.date for bar in bars]
            for code, bars in ordered_bars.items()
        }

        def history_fn(code: str, field: str, n: int, asof) -> list[float]:
            dates = code_dates.get(code, [])
            index = bisect.bisect_right(dates, asof)
            bars = ordered_bars.get(code, [])
            start = max(0, index - n)
            window = bars[start:index]
            return [float(getattr(bar, field)) for bar in window]

        broker = Broker(config.initial_capital, config.slippage)
        for code, bars in ordered_bars.items():
            if bars[0].previous_close is not None:
                broker.seed_previous_close(code, bars[0].previous_close)
        context = Context(broker, config.params, history_fn, universe=config.codes)
        equity_curve: list[dict] = []

        code_order = list(ordered_bars)
        adapter = self._strategy_adapter(bt)
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(config.initial_capital)
        cerebro.addstrategy(
            adapter,
            host_strategy=strategy,
            context=context,
            execution_broker=broker,
            bars_by_code=ordered_bars,
            code_order=code_order,
            equity_curve=equity_curve,
        )
        for code in code_order:
            frame = self._to_frame(ordered_bars[code])
            timeframe = bt.TimeFrame.Days if config.frequency == "1d" else bt.TimeFrame.Minutes
            feed = bt.feeds.PandasData(
                dataname=frame,
                datetime=None,
                open="open",
                high="high",
                low="low",
                close="close",
                volume="volume",
                openinterest=None,
                timeframe=timeframe,
                compression=self._compression(config.frequency),
            )
            cerebro.adddata(feed, name=code)

        cerebro.run(runonce=False, preload=True)
        return EngineResult(
            equity_curve=equity_curve,
            fills=broker.fills,
            data_quality={code: "provided" for code in code_order},
        )

    @staticmethod
    def _compression(frequency: str) -> int:
        return 1 if frequency == "1d" else int(frequency.removesuffix("m"))

    @staticmethod
    def _to_frame(bars: list[Bar]) -> pd.DataFrame:
        index = pd.DatetimeIndex(pd.Timestamp(bar.date) for bar in bars)
        return pd.DataFrame(
            {
                "open": [bar.open for bar in bars],
                "high": [bar.high for bar in bars],
                "low": [bar.low for bar in bars],
                "close": [bar.close for bar in bars],
                "volume": [bar.volume for bar in bars],
            },
            index=index,
        )

    @staticmethod
    def _strategy_adapter(bt):
        class CerebroStrategyAdapter(bt.Strategy):
            params = (
                ("host_strategy", None),
                ("context", None),
                ("execution_broker", None),
                ("bars_by_code", None),
                ("code_order", None),
                ("equity_curve", None),
            )

            def __init__(self) -> None:
                self._seen = {code: 0 for code in self.p.code_order}
                self.p.host_strategy.initialize(self.p.context)

            def prenext(self) -> None:
                self._dispatch()

            def nextstart(self) -> None:
                self._dispatch()

            def next(self) -> None:
                self._dispatch()

            def _dispatch(self) -> None:
                changed: dict[str, Bar] = {}
                for data, code in zip(self.datas, self.p.code_order, strict=True):
                    size = len(data)
                    if size <= self._seen[code]:
                        continue
                    self._seen[code] = size
                    changed[code] = self.p.bars_by_code[code][size - 1]
                if not changed:
                    return

                when = max(bar.date for bar in changed.values())
                ledger = self.p.execution_broker
                ledger.settle_t1(when)
                ledger.execute_open(changed, when)
                self.p.context._set_date(when)
                self.p.host_strategy.handle_bar(self.p.context, changed)
                equity = round(ledger.mark_to_market(changed), 2)
                cash = round(ledger.cash, 2)
                self.p.equity_curve.append(
                    {
                        "date": when.isoformat(),
                        "equity": equity,
                        "cash": cash,
                        "marketValue": round(equity - cash, 2),
                    }
                )

        return CerebroStrategyAdapter
