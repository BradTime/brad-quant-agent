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
    _attach_benchmark(computed, bars_by_code, config.start, config.end)
    computed["dataQuality"] = data_quality
    computed["engine"] = engine.name
    return computed


_BENCHMARK_INDEX = "000300.SH"


def _attach_benchmark(computed: dict, bars_by_code: dict, start: str, end: str) -> None:
    """给权益曲线叠加基准并算超额：优先沪深300指数，无指数数据则降级为标的等权买入持有。

    基准/超额写入 ``metrics``（随结果落库与返回），权益点追加 ``benchmark`` 字段供前端叠加。
    """
    curve: dict[str, float] = {}
    label: str | None = None
    idx_bars, _ = load_hfq_bars(_BENCHMARK_INDEX, start, end)
    if idx_bars and idx_bars[0].close > 0:
        base = idx_bars[0].close
        curve = {b.date.isoformat(): (b.close / base - 1) * 100 for b in idx_bars}
        label = "沪深300"
    else:  # 降级：标的等权买入持有（衡量策略是否跑赢"躺平持有"）
        norm: dict[str, dict[str, float]] = {}
        for code, bars in bars_by_code.items():
            if bars and bars[0].close > 0:
                base = bars[0].close
                norm[code] = {b.date.isoformat(): (b.close / base - 1) * 100 for b in bars}
        for d in {dd for mm in norm.values() for dd in mm}:
            vals = [norm[c][d] for c in norm if d in norm[c]]
            if vals:
                curve[d] = sum(vals) / len(vals)
        if curve:
            label = "买入持有"
    if not curve:
        return
    last = 0.0
    for pt in computed.get("equityCurve", []):
        b = curve.get(pt["date"])
        if b is not None:
            pt["benchmark"] = round(b, 2)
            last = b
    m = computed.get("metrics", {})
    m["benchmarkLabel"] = label
    m["benchmarkReturnPercent"] = round(last, 2)
    m["excessReturnPercent"] = round(m.get("totalReturnPercent", 0.0) - last, 2)
