"""策略上下文：策略经此下单 / 查持仓 / 取历史窗口。

``history`` 只返回 **截至当日（含）** 的数据，从接口层面杜绝未来函数。
下单为"意图"，由引擎在次日开盘撮合（见 ``broker``）。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.backtest.broker import Broker


class Context:
    def __init__(
        self,
        broker: Broker,
        params: dict | None,
        history_fn: Callable[[str, str, int, date], list[float]],
    ) -> None:
        self.broker = broker
        self.params = params or {}
        self._history_fn = history_fn
        self.current_date: date | None = None

    def _set_date(self, d: date) -> None:
        self.current_date = d

    @property
    def portfolio(self) -> dict:
        return {
            "cash": round(self.broker.cash, 2),
            "positions": {c: p.qty for c, p in self.broker.positions.items() if p.qty > 0},
        }

    def history(self, code: str, field: str = "close", n: int = 20) -> list[float]:
        """截至当日的最近 n 个 field 值（含当日；不含未来）。"""
        return self._history_fn(code, field, n, self.current_date)

    def order_shares(self, code: str, shares: int) -> None:
        self.broker.submit_shares(code, int(shares))

    def order_target_percent(self, code: str, pct: float) -> None:
        self.broker.submit_target_percent(code, float(pct))
