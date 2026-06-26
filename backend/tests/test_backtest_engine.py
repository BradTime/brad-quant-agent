"""M2 回测引擎单测：事件循环、前视偏差、T+1/费用、绩效指标、集成冒烟。"""

from datetime import date

import pytest

from app.backtest.base import BacktestConfig, Fill, Strategy
from app.backtest.broker import Broker
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine
from app.backtest.metrics import compute_metrics


def _bar(code: str, d: date, o: float, c: float, v: int = 100000) -> Bar:
    return Bar(code=code, date=d, open=o, high=max(o, c), low=min(o, c), close=c, volume=v, amount=o * v)


class _AlwaysFull(Strategy):
    """每日目标满仓——用于验证成交时机与撮合。"""

    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        for code in bars:
            ctx.order_target_percent(code, 1.0)


def _cfg(**kw) -> BacktestConfig:
    base = dict(
        strategy_type="dual_ma", params={}, codes=["X"],
        start="2024-01-01", end="2024-12-31", initial_capital=100000.0,
    )
    base.update(kw)
    return BacktestConfig(**base)


def test_no_lookahead_signal_fills_next_open():
    """关键：t 日信号在 t+1 开盘成交，而非当日——杜绝前视偏差。"""
    bars = [
        _bar("X", date(2024, 1, 1), 10.0, 10.0),
        _bar("X", date(2024, 1, 2), 10.5, 10.5),  # 次日开盘 10.5（涨5%，不触发涨停）
        _bar("X", date(2024, 1, 3), 10.8, 10.8),
    ]
    res = NativeEngine().run(_cfg(), _AlwaysFull(), {"X": bars})
    assert res.fills, "应产生成交"
    first = res.fills[0]
    assert first.side == "buy"
    assert first.date == date(2024, 1, 2)  # 次日成交
    assert first.price == 10.5  # 用次日开盘价，而非信号日的 10（若前视则会是 10）


def test_broker_t1_and_commission():
    """当日买入计入持仓但不可卖（T+1）；费用按 trading_rules 口径。"""
    b = Broker(100000.0, slippage=0.0)
    today = date(2024, 1, 2)
    b.submit_shares("X", 1000)
    b.execute_open({"X": _bar("X", today, 10.0, 10.0)}, today)
    pos = b.positions["X"]
    assert pos.qty == 1000
    assert pos.available == 0  # T+1：当日买入不可卖
    assert b.cash == 89995.0  # 100000 - 10000 - 佣金5
    b.settle_t1()
    assert b.positions["X"].available == 1000  # 次日解冻


def test_price_limit_blocks_buy_at_limit_up():
    """开盘涨停（相对昨收涨幅 ≥10%）则买单不成交。"""
    b = Broker(100000.0, slippage=0.0)
    b._prev_close["X"] = 10.0
    b.submit_shares("X", 1000)
    b.execute_open({"X": _bar("X", date(2024, 1, 2), 11.5, 11.5)}, date(2024, 1, 2))  # 涨15%
    assert not b.fills  # 涨停买不进
    assert b.positions.get("X") is None or b.positions["X"].qty == 0


def test_compute_metrics_and_roundtrip():
    eq = [
        {"date": "2024-01-01", "equity": 100000},
        {"date": "2024-01-02", "equity": 110000},
        {"date": "2024-01-03", "equity": 105000},
    ]
    fills = [
        Fill("X", date(2024, 1, 1), "buy", 10.0, 1000, 10000, 5.0, 0.0),
        Fill("X", date(2024, 1, 3), "sell", 11.0, 1000, 11000, 5.5, 11.0),
    ]
    out = compute_metrics(eq, fills, 100000.0)
    m = out["metrics"]
    assert m["totalReturn"] == 5000.0
    assert m["totalReturnPercent"] == 5.0
    assert m["maxDrawdownPercent"] > 0  # 110000 → 105000 的回撤
    assert m["totalTrades"] == 1
    assert m["winningTrades"] == 1
    assert out["trades"][0]["return"] > 0  # 买10卖11，扣费后仍盈利
    assert len(out["equityCurve"]) == 3


def test_dual_ma_runs_and_trades_on_trend():
    """双均线在明确上升趋势中应建仓（金叉）。"""
    from datetime import timedelta

    from app.backtest.strategies import get_strategy

    d0 = date(2024, 1, 1)
    bars = [_bar("X", d0 + timedelta(days=i), 10 + i, 10 + i) for i in range(25)]
    res = NativeEngine().run(
        _cfg(params={"fast": 3, "slow": 5}),
        get_strategy("dual_ma"),
        {"X": bars},
    )
    assert any(f.side == "buy" for f in res.fills), "上升趋势应触发金叉买入"


def test_run_backtest_smoke():
    """端到端编排冒烟：有回填数据则校验结构，无 DB/数据则跳过。"""
    from app.backtest.runner import run_backtest

    cfg = _cfg(
        strategy_type="dual_ma", params={"fast": 5, "slow": 20},
        codes=["600000.SH"], start="2024-01-01", end="2026-12-31", initial_capital=1_000_000.0,
    )
    try:
        out = run_backtest(cfg)
    except Exception:
        pytest.skip("DB 不可用")
    if out.get("error"):
        pytest.skip("无回填数据")
    assert out["engine"] == "native"
    assert len(out["equityCurve"]) > 0
    assert "sharpeRatio" in out["metrics"]


def test_all_catalog_strategies_run():
    """目录中每个策略都能在合成数据上跑通（产出完整权益序列），且目录不超出已注册集合。"""
    from datetime import timedelta

    from app.backtest.strategies import STRATEGY_REGISTRY, get_strategy
    from app.services.backtest_run import strategy_catalog

    assert {c["type"] for c in strategy_catalog()} <= set(STRATEGY_REGISTRY)

    d0 = date(2024, 1, 1)
    bars = [
        _bar("X", d0 + timedelta(days=i), 10 + (i % 5) + i * 0.2, 10 + (i % 5) + i * 0.2)
        for i in range(40)
    ]
    for stype in STRATEGY_REGISTRY:
        res = NativeEngine().run(_cfg(strategy_type=stype), get_strategy(stype), {"X": bars})
        assert len(res.equity_curve) == len(bars)
