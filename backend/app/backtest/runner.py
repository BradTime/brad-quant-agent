"""回测编排：加载后复权数据 → 选引擎 → 跑 → 算指标 → 组装（对齐前端契约）。

供 service / API 层调用；纯同步、可单测。数据缺失时优雅返回错误（不杜撰）。
"""

from __future__ import annotations

from app.backtest.base import BacktestConfig
from app.backtest.data import load_hfq_bars
from app.backtest.metrics import compute_metrics
from app.backtest.registry import get_engine
from app.backtest.strategies import get_strategy


def run_backtest(config: BacktestConfig) -> dict:
    bars_by_code: dict[str, list] = {}
    data_quality: dict[str, str] = {}
    for code in config.codes:
        bars, coverage = load_hfq_bars(code, config.start, config.end)
        data_quality[code] = coverage
        if bars:
            bars_by_code[code] = bars

    if not bars_by_code:
        return {
            "metrics": {},
            "equityCurve": [],
            "trades": [],
            "dataQuality": data_quality,
            "error": "无可用行情数据（请先 backfill 对应标的与区间）",
        }

    strategy = get_strategy(config.strategy_type)
    engine = get_engine(config.engine)
    result = engine.run(config, strategy, bars_by_code)

    computed = compute_metrics(result.equity_curve, result.fills, config.initial_capital)
    computed["dataQuality"] = data_quality
    computed["engine"] = engine.name
    return computed
