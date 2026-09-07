"""绩效指标 + round-trip 成交配对（对齐前端 BacktestMetrics / EquityPoint / TradeRecord）。

纯计算（无 numpy 依赖）。年化按 252 交易日；夏普/索提诺无风险利率取 0。
成交按 FIFO 把买卖配成平仓回合，逐回合算净盈亏（含分摊费用/印花税）。
"""

from __future__ import annotations

import math
from collections import defaultdict, deque

from app.backtest.base import Fill

_TRADING_DAYS = 252


def _sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    return round(mean / std * math.sqrt(_TRADING_DAYS), 4) if std > 0 else 0.0


def _sortino(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        return 0.0
    dstd = math.sqrt(sum(r**2 for r in downside) / len(rets))
    return round(mean / dstd * math.sqrt(_TRADING_DAYS), 4) if dstd > 0 else 0.0


def _max_drawdown(eqs: list[float]) -> float:
    peak = eqs[0] if eqs else 0.0
    mdd = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def _pair_trades(fills: list[Fill]) -> list[dict]:
    """FIFO 配对：买入入队，卖出逐笔配对最早未平仓买入，算每回合净盈亏。"""
    lots: dict[str, deque] = defaultdict(deque)  # code -> [px, remain, orig, fee, date]
    trades: list[dict] = []
    tid = 0
    for f in sorted(fills, key=lambda x: (x.date, 0 if x.side == "buy" else 1)):
        if f.side == "buy":
            lots[f.code].append([f.price, f.qty, f.qty, f.fee, f.date])
            continue
        remaining = f.qty
        sell_fee_per = (f.fee + f.tax) / f.qty if f.qty else 0.0
        while remaining > 0 and lots[f.code]:
            lot = lots[f.code][0]
            match = min(remaining, lot[1])
            buy_fee_share = lot[3] * match / lot[2] if lot[2] else 0.0
            cost = lot[0] * match
            pnl = (f.price - lot[0]) * match - buy_fee_share - sell_fee_per * match
            tid += 1
            trades.append(
                {
                    "id": str(tid),
                    "symbol": f.code,
                    "side": "buy",
                    "quantity": match,
                    "entryPrice": round(lot[0], 4),
                    "exitPrice": round(f.price, 4),
                    "entryTime": lot[4].isoformat(),
                    "exitTime": f.date.isoformat(),
                    "return": round(pnl, 2),
                    "returnPercent": round(pnl / cost * 100, 2) if cost else 0.0,
                    "commission": round(buy_fee_share + sell_fee_per * match, 2),
                }
            )
            lot[1] -= match
            remaining -= match
            if lot[1] <= 0:
                lots[f.code].popleft()
    return trades


def compute_metrics(
    equity_curve: list[dict],
    fills: list[Fill],
    initial: float,
    *,
    return_curve: list[dict] | None = None,
) -> dict:
    eqs = [p["equity"] for p in equity_curve]
    sampled_eqs = [p["equity"] for p in (return_curve or equity_curve)]
    n = len(sampled_eqs)
    final = eqs[-1] if eqs else initial
    total_return = final - initial
    total_return_pct = (total_return / initial * 100) if initial else 0.0
    return_eqs = [initial, *sampled_eqs]
    rets = [
        return_eqs[i] / return_eqs[i - 1] - 1
        for i in range(1, len(return_eqs))
        if return_eqs[i - 1] > 0
    ]
    annual = ((final / initial) ** (_TRADING_DAYS / n) - 1) * 100 if n > 1 and initial > 0 and final > 0 else 0.0

    trades = _pair_trades(fills)
    wins = [t for t in trades if t["return"] > 0]
    losses = [t for t in trades if t["return"] <= 0]
    gross_win = sum(t["return"] for t in wins)
    gross_loss = -sum(t["return"] for t in losses)

    mdd = _max_drawdown(eqs)
    peak = max(eqs) if eqs else 0.0
    equity_points = [
        {
            "date": p["date"],
            "equity": round(p["equity"], 2),
            "return": round(p["equity"] - initial, 2),
            "returnPercent": round((p["equity"] - initial) / initial * 100, 2) if initial else 0.0,
        }
        for p in equity_curve
    ]

    metrics = {
        "totalReturn": round(total_return, 2),
        "totalReturnPercent": round(total_return_pct, 2),
        "annualReturn": round(initial * annual / 100, 2),
        "annualReturnPercent": round(annual, 2),
        "sharpeRatio": _sharpe(rets),
        "sortinoRatio": _sortino(rets),
        "maxDrawdown": round(peak * mdd, 2),
        "maxDrawdownPercent": round(mdd * 100, 2),
        "winRate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "profitFactor": round(gross_win / gross_loss, 4) if gross_loss > 0 else 0.0,
        "averageWin": round(gross_win / len(wins), 2) if wins else 0.0,
        "averageLoss": round(gross_loss / len(losses), 2) if losses else 0.0,
        "totalTrades": len(trades),
        "winningTrades": len(wins),
        "losingTrades": len(losses),
    }
    return {"metrics": metrics, "equityCurve": equity_points, "trades": trades}
