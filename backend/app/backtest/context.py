"""策略上下文：策略经此下单 / 查持仓 / 取历史窗口。

``history`` 只返回 **截至当前 bar（含）** 的数据，从接口层面杜绝未来函数。
下单为"意图"，由引擎在下一根 bar 开盘撮合（见 ``broker``）。
"""

from __future__ import annotations

import bisect
from collections.abc import Callable
from datetime import UTC, date, datetime, time

from app.backtest.broker import Broker
from app.core.tz import MARKET_TZ


def make_panel_history_reader(
    panels: dict[str, dict[str, list[dict]]],
) -> Callable[[str, str, int, date | datetime | None], list[dict]]:
    prepared: dict[tuple[str, str], list[tuple[datetime, str, dict]]] = {}
    for panel, by_code in panels.items():
        for code, rows in by_code.items():
            values: list[tuple[datetime, str, dict]] = []
            for row in rows:
                row_date = str(row.get("date", ""))[:10]
                available_raw = row.get("availableAt")
                if not row_date or not available_raw:
                    continue
                try:
                    available_at = datetime.fromisoformat(
                        str(available_raw).replace("Z", "+00:00")
                    )
                except ValueError:
                    continue
                if available_at.tzinfo is None:
                    available_at = available_at.replace(tzinfo=UTC)
                values.append(
                    (available_at.astimezone(UTC), row_date, row)
                )
            prepared[(panel, code)] = sorted(
                values, key=lambda item: (item[0], item[1])
            )
    state: dict[tuple[str, str], dict] = {}

    def read(
        code: str,
        panel: str,
        n: int,
        as_of: date | datetime | None,
    ) -> list[dict]:
        if as_of is None:
            return []
        day = as_of.date() if isinstance(as_of, datetime) else as_of
        cutoff = datetime.combine(
            day, time.max, tzinfo=MARKET_TZ
        ).astimezone(UTC)
        key = (panel, code)
        current = state.get(key)
        if current is None or day < current["day"]:
            current = {
                "day": day,
                "cursor": 0,
                "dates": [],
                "latest": {},
            }
            state[key] = current
        rows = prepared.get(key, [])
        while (
            current["cursor"] < len(rows)
            and rows[current["cursor"]][0] <= cutoff
        ):
            _, row_date, row = rows[current["cursor"]]
            if row_date not in current["latest"]:
                bisect.insort(current["dates"], row_date)
            current["latest"][row_date] = row
            current["cursor"] += 1
        current["day"] = day
        end = bisect.bisect_right(current["dates"], day.isoformat())
        selected = current["dates"][max(0, end - max(int(n), 0)) : end]
        return [current["latest"][row_date] for row_date in selected]

    return read


def panel_history_from_data(
    panels: dict[str, dict[str, list[dict]]],
    code: str,
    panel: str,
    n: int,
    as_of: date | datetime | None,
) -> list[dict]:
    return make_panel_history_reader(panels)(code, panel, n, as_of)


class Context:
    def __init__(
        self,
        broker: Broker,
        params: dict | None,
        history_fn: Callable[[str, str, int, date | datetime], list[float]],
        panel_history_fn: (
            Callable[[str, str, int, date | datetime], list[dict]] | None
        ) = None,
        universe: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.broker = broker
        self.params = params or {}
        self._history_fn = history_fn
        self._panel_history_fn = panel_history_fn
        self.universe = tuple(universe or ())
        self.current_date: date | datetime | None = None

    def _set_date(self, d: date | datetime) -> None:
        self.current_date = d

    def set_universe(self, codes: list[str] | tuple[str, ...]) -> None:
        self.universe = tuple(codes)

    @property
    def portfolio(self) -> dict:
        return {
            "cash": round(self.broker.cash, 2),
            "positions": {c: p.qty for c, p in self.broker.positions.items() if p.qty > 0},
        }

    def history(self, code: str, field: str = "close", n: int = 20) -> list[float]:
        """截至当前 bar 的最近 n 个 field 值（含当前；不含未来）。"""
        return self._history_fn(code, field, n, self.current_date)

    def panel_history(
        self, code: str, panel: str, n: int = 20
    ) -> list[dict]:
        if self._panel_history_fn is None:
            return []
        return self._panel_history_fn(code, panel, n, self.current_date)

    def order_shares(self, code: str, shares: int) -> None:
        self.broker.submit_shares(code, int(shares))

    def order_target_percent(self, code: str, pct: float) -> None:
        self.broker.submit_target_percent(code, float(pct))
