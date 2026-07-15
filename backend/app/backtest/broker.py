"""native 引擎的撮合账户。

复用 ``trading_rules`` 的 A 股口径：100 股整手、佣金万2.5(最低5)、卖出印花税千1、
T+1（当日买入次日可卖）、涨跌停（开盘越限则该方向不成交）、滑点（买抬卖压）。

成交时机：策略在 t 根 bar ``submit_*`` 的意图，由引擎在 **t+1 根 bar 开盘**
``execute_open`` 成交，规避前视偏差。``mark_to_market`` 按当前 bar 收盘记权益。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.backtest.base import Fill
from app.backtest.data import Bar
from app.services import trading_rules as rules


@dataclass
class Position:
    qty: int = 0
    available: int = 0  # 可卖（T+1：当日买入计入 qty 但不计入 available）
    avg_cost: float = 0.0


class Broker:
    def __init__(self, initial_cash: float, slippage: float = 0.0) -> None:
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: dict[str, Position] = {}
        self.slippage = max(slippage, 0.0)
        self.fills: list[Fill] = []
        self._pending: list[tuple[str, str, float]] = []  # (kind, code, value)
        self._prev_close: dict[str, float] = {}
        self._last_settlement_day: date | None = None
        self._market_day: date | None = None
        self._current_day_close: dict[str, float] = {}
        self._last_price: dict[str, float] = {}

    # ---- 策略下单意图（下一根 bar 开盘成交） ----
    def submit_shares(self, code: str, delta_shares: int) -> None:
        self._pending.append(("shares", code, float(int(delta_shares))))

    def submit_target_percent(self, code: str, pct: float) -> None:
        self._pending.append(("target", code, float(pct)))

    def seed_previous_close(self, code: str, close: float) -> None:
        """Seed the pre-window close used for first-day price-limit checks."""
        if close > 0:
            self._prev_close[code] = float(close)

    # ---- 撮合与自然日结算 ----
    def settle_t1(self, trade_time: date | datetime | None = None) -> None:
        """仅跨自然交易日解冻；无参数调用保留显式手工结算语义。"""
        if trade_time is not None:
            trade_day = trade_time.date() if isinstance(trade_time, datetime) else trade_time
            if self._last_settlement_day is None:
                self._last_settlement_day = trade_day
                return
            if trade_day == self._last_settlement_day:
                return
            self._last_settlement_day = trade_day
        for p in self.positions.values():
            p.available = p.qty

    def _value(self, price_of: dict[str, float]) -> float:
        mv = sum(
            p.qty
            * price_of.get(
                c,
                self._last_price.get(
                    c,
                    self._current_day_close.get(c, self._prev_close.get(c, p.avg_cost)),
                ),
            )
            for c, p in self.positions.items()
        )
        return self.cash + mv

    def execute_open(
        self,
        bars_today: dict[str, Bar],
        trade_date: date | datetime,
    ) -> None:
        """处理上一根 bar 的意图，用当前开盘价成交。卖单先行以释放资金。"""
        trade_day = trade_date.date() if isinstance(trade_date, datetime) else trade_date
        if self._market_day is None:
            self._market_day = trade_day
        elif trade_day != self._market_day:
            self._prev_close.update(self._current_day_close)
            self._current_day_close.clear()
            self._market_day = trade_day
        open_px = {c: b.open for c, b in bars_today.items()}
        self._last_price.update(open_px)
        total = self._value(open_px)
        orders: list[tuple[str, int, float]] = []
        pending: list[tuple[str, str, float]] = []
        for kind, code, val in self._pending:
            bar = bars_today.get(code)
            if bar is None or bar.open <= 0:
                pending.append((kind, code, val))
                continue  # 等待该标的自己的下一根 bar
            px = bar.open
            if kind == "target":
                target = rules.round_lot(int(total * val / px))
                cur = self.positions.get(code, Position()).qty
                delta = target - cur
            else:
                delta = rules.round_lot(int(val)) if val >= 0 else -rules.round_lot(int(-val))
            if delta != 0:
                orders.append((code, delta, px))
        orders.sort(key=lambda o: o[1])  # 负(卖)在前
        for code, delta, px in orders:
            self._fill(code, delta, px, trade_date)
        self._pending = pending
        for c, b in bars_today.items():
            self._current_day_close[c] = b.close
            self._last_price[c] = b.close

    def _limit_blocked(self, code: str, side: str, px: float) -> bool:
        prev = self._prev_close.get(code)
        if not prev or prev <= 0:
            return False
        ratio = rules.price_limit_ratio(code)
        if side == "buy" and px >= round(prev * (1 + ratio), 2):
            return True  # 开盘涨停，买不进
        if side == "sell" and px <= round(prev * (1 - ratio), 2):
            return True  # 开盘跌停，卖不出
        return False

    def _fill(
        self,
        code: str,
        delta: int,
        px: float,
        trade_date: date | datetime,
    ) -> None:
        side = "buy" if delta > 0 else "sell"
        if self._limit_blocked(code, side, px):
            return
        fill_px = round(px * (1 + self.slippage), 4) if side == "buy" else round(px * (1 - self.slippage), 4)
        pos = self.positions.setdefault(code, Position())
        qty = abs(delta)
        if side == "buy":
            qty = rules.round_lot(qty)
            if qty <= 0:
                return
            amount = fill_px * qty
            total = amount + rules.commission(amount)
            if total > self.cash:  # 资金不足：按可买整手缩减
                qty = rules.round_lot(int(self.cash / (fill_px * (1 + rules.COMMISSION_RATE))))
                if qty <= 0:
                    return
                amount = fill_px * qty
                total = amount + rules.commission(amount)
            fee = rules.commission(amount)
            self.cash = rules.round_money(self.cash - amount - fee)
            new_qty = pos.qty + qty
            pos.avg_cost = round((pos.avg_cost * pos.qty + amount + fee) / new_qty, 4)
            pos.qty = new_qty
            tax = 0.0
        else:
            qty = min(rules.round_lot(qty), pos.available)
            if qty <= 0:
                return
            amount = fill_px * qty
            fee = rules.commission(amount)
            tax = rules.stamp_tax(amount, "sell")
            self.cash = rules.round_money(self.cash + amount - fee - tax)
            pos.qty -= qty
            pos.available -= qty
            if pos.qty <= 0:
                pos.qty = 0
                pos.available = max(pos.available, 0)
                pos.avg_cost = 0.0
        self.fills.append(
            Fill(
                code=code, date=trade_date, side=side, price=fill_px, qty=qty,
                amount=round(fill_px * qty, 2), fee=round(fee, 2), tax=round(tax, 2),
            )
        )

    def mark_to_market(self, bars_today: dict[str, Bar]) -> float:
        closes = {c: b.close for c, b in bars_today.items()}
        self._last_price.update(closes)
        return self._value(closes)
