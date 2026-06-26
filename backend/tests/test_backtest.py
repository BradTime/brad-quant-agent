"""回测引擎 M1 单测：后复权阶梯因子、引擎注册表、native/backtrader 骨架。"""

from datetime import date

import pytest

from app.backtest.base import BacktestConfig


def _cfg() -> BacktestConfig:
    return BacktestConfig(
        strategy_type="dual_ma", params={}, codes=["600000.SH"],
        start="2024-01-01", end="2024-12-31",
    )


def test_factor_at_step():
    """后复权因子按 ex_date 阶梯选择：早于首个用 1.0，区间内用前一个，命中用当前。"""
    from app.backtest.data import _factor_at

    points = [(date(2024, 1, 10), 1.0), (date(2024, 6, 1), 1.2)]
    days = [p[0] for p in points]
    assert _factor_at(points, days, date(2024, 1, 1)) == 1.0   # 早于首个除权日
    assert _factor_at(points, days, date(2024, 1, 10)) == 1.0  # 命中首个
    assert _factor_at(points, days, date(2024, 3, 1)) == 1.0   # 两除权日之间
    assert _factor_at(points, days, date(2024, 6, 1)) == 1.2   # 命中第二个
    assert _factor_at(points, days, date(2024, 12, 1)) == 1.2  # 最后一个之后


def test_get_engine_native_default():
    from app.backtest.registry import get_engine

    assert get_engine().name == "native"
    assert get_engine("native").name == "native"


def test_get_engine_unknown_raises():
    from app.backtest.registry import get_engine

    with pytest.raises(ValueError):
        get_engine("nope")


def test_native_run_not_implemented_in_m1():
    from app.backtest.engines.native import NativeEngine

    with pytest.raises(NotImplementedError):
        NativeEngine().run(_cfg(), None, {})


def test_backtrader_engine_reserved():
    """预留引擎可被选择，但 run() 在未安装/未实现时报错（不静默）。"""
    from app.backtest.registry import get_engine

    eng = get_engine("backtrader")
    assert eng.name == "backtrader"
    with pytest.raises((RuntimeError, NotImplementedError)):
        eng.run(_cfg(), None, {})


def test_load_hfq_smoke():
    """后复权加载冒烟：有数据则校验有序/正价，无数据或无 DB 则跳过。"""
    from app.backtest.data import load_hfq_bars

    try:
        bars, coverage = load_hfq_bars("600000.SH", "2024-01-01", "2026-12-31")
    except Exception:
        pytest.skip("DB 不可用")
    if not bars:
        pytest.skip("无回填数据")
    assert coverage in ("full", "none")
    assert all(b.close > 0 for b in bars)
    assert [b.date for b in bars] == sorted(b.date for b in bars)
