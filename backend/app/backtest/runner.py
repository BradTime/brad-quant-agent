"""回测编排：加载后复权数据 → 选引擎 → 跑 → 算指标 → 组装（对齐前端契约）。

供 service / API 层调用；纯同步、可单测。数据缺失时优雅返回错误（不杜撰）。
``load_bars`` / ``load_benchmark`` / ``run_on_bars`` 分离，使网格寻优可
**只加载一次行情、多组参数复用**（避免 N 组重复读库）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from app.backtest.base import BacktestConfig
from app.backtest.data import Bar, load_hfq_bars, load_minute_bars
from app.backtest.metrics import compute_metrics
from app.backtest.registry import get_engine
from app.backtest.strategies import get_strategy

_BENCHMARK_INDEX = "000300.SH"
_RULE_QUALITY = {
    "historicalST": "unavailable",
    "priceLimit": "board-rules; ST 5% only when a per-bar PIT limit ratio is supplied",
}


def load_bars(config: BacktestConfig) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    """按配置加载各标的后复权日线或分钟线（含数据质量标注）。"""
    bars_by_code: dict[str, list[Bar]] = {}
    data_quality: dict[str, str] = {}
    for code in config.codes:
        if config.frequency == "1d":
            bars, coverage = load_hfq_bars(code, config.start, config.end)
        else:
            bars, coverage = load_minute_bars(
                code,
                config.frequency,
                config.start,
                config.end,
            )
        data_quality[code] = coverage
        if bars:
            bars_by_code[code] = bars
    return bars_by_code, data_quality


def load_benchmark(start: str, end: str) -> list[Bar]:
    """预加载基准指数日线（供 run_on_bars 复用；网格寻优避免重复加载）。"""
    warm_start = (date.fromisoformat(start[:10]) - timedelta(days=14)).isoformat()
    bars, _ = load_hfq_bars(_BENCHMARK_INDEX, warm_start, end)
    return bars


def run_on_bars(
    config: BacktestConfig,
    bars_by_code: dict[str, list[Bar]],
    data_quality: dict[str, str],
    benchmark_bars: list[Bar] | None = None,
) -> dict:
    """在**已加载**的行情上跑单次回测（网格寻优对每组参数复用同一份数据）。"""
    aligned_bars, actual_range = _align_bars_to_common_range(bars_by_code)
    if aligned_bars is None or actual_range is None:
        return {
            "metrics": {},
            "equityCurve": [],
            "trades": [],
            "dataQuality": data_quality,
            "error": "所选标的没有共同可回测区间",
        }
    range_start, range_end = actual_range
    strategy = get_strategy(config.strategy_type)
    engine = get_engine(config.engine)
    try:
        result = engine.run(config, strategy, aligned_bars)
    except RuntimeError as exc:
        message = str(exc)
        dependency_missing = engine.name == "backtrader" and (
            "未安装" in message or "pip install backtrader" in message
        )
        if not dependency_missing:
            raise
        return {
            "metrics": {},
            "equityCurve": [],
            "trades": [],
            "dataQuality": data_quality,
            "engine": engine.name,
            "actualRange": {
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
            },
            "error": message,
        }
    return_curve = (
        _daily_close_equity(result.equity_curve)
        if config.frequency != "1d"
        else result.equity_curve
    )
    computed = compute_metrics(
        result.equity_curve,
        result.fills,
        config.initial_capital,
        return_curve=return_curve,
    )
    _attach_benchmark(computed, aligned_bars, config.start, config.end, benchmark_bars)
    computed["dataQuality"] = data_quality
    computed["ruleQuality"] = dict(_RULE_QUALITY)
    computed["engine"] = engine.name
    computed["actualRange"] = {
        "start": range_start.isoformat(),
        "end": range_end.isoformat(),
    }
    return computed


def _daily_close_equity(equity_curve: list[dict]) -> list[dict]:
    """Collapse intraday marks to the final equity point of each trading day."""
    by_day: dict[str, dict] = {}
    for point in equity_curve:
        by_day[str(point["date"])[:10]] = point
    return list(by_day.values())


def _common_data_range(bars_by_code: dict[str, list[Bar]]):
    """Return the overlapping first/last bar range shared by every symbol."""
    populated = [bars for bars in bars_by_code.values() if bars]
    if not populated or len(populated) != len(bars_by_code):
        return None
    start = max(bars[0].date for bars in populated)
    end = min(bars[-1].date for bars in populated)
    return (start, end) if start <= end else None


def _align_bars_to_common_range(
    bars_by_code: dict[str, list[Bar]],
) -> tuple[dict[str, list[Bar]] | None, tuple | None]:
    """Align all symbols to a non-empty common range and preserve limit seeds."""
    actual_range = _common_data_range(bars_by_code)
    if actual_range is None:
        return None, None
    range_start, range_end = actual_range
    aligned: dict[str, list[Bar]] = {}
    target_day = range_start.date() if hasattr(range_start, "date") else range_start
    for code, bars in bars_by_code.items():
        selected = [bar for bar in bars if range_start <= bar.date <= range_end]
        if not selected:
            return None, actual_range
        seed = bars[0].previous_close
        prior_sessions = [
            bar
            for bar in bars
            if (bar.date.date() if hasattr(bar.date, "date") else bar.date) < target_day
        ]
        if prior_sessions:
            seed = prior_sessions[-1].close
        selected[0] = replace(selected[0], previous_close=seed)
        aligned[code] = selected
    return aligned, actual_range


def run_backtest(config: BacktestConfig) -> dict:
    bars_by_code, data_quality = load_bars(config)
    missing = unusable_data_codes(config, bars_by_code, data_quality)
    if missing:
        return {
            "metrics": {},
            "equityCurve": [],
            "trades": [],
            "dataQuality": data_quality,
            "error": missing_data_error(config, missing, data_quality),
        }
    return run_on_bars(config, bars_by_code, data_quality)


def unusable_data_codes(
    config: BacktestConfig,
    bars_by_code: dict[str, list[Bar]],
    data_quality: dict[str, str],
) -> list[str]:
    unusable_quality = {"missing", "missing_previous_close"}
    return [
        code
        for code in config.codes
        if code not in bars_by_code or data_quality.get(code) in unusable_quality
    ]


def missing_data_error(
    config: BacktestConfig,
    codes: list[str] | None = None,
    data_quality: dict[str, str] | None = None,
) -> str:
    suffix = f"；缺失标的: {', '.join(codes)}" if codes else ""
    if data_quality and any(
        data_quality.get(code) == "missing_previous_close" for code in (codes or [])
    ):
        return f"缺少回测起点前一交易日收盘，无法可靠判断涨跌停{suffix}"
    if config.frequency == "1d":
        return f"无可用行情数据（请先 backfill 对应标的与区间）{suffix}"
    return (
        f"无可用 {config.frequency} 分钟行情数据"
        "（请先 backfill minute 对应标的、周期与区间；不会自动实时抓取）"
        f"{suffix}"
    )


def _attach_benchmark(
    computed: dict,
    bars_by_code: dict,
    start: str,
    end: str,
    benchmark_bars: list[Bar] | None = None,
) -> None:
    """给权益曲线叠加基准并算超额：优先沪深300指数，无指数数据则降级为标的等权买入持有。

    ``benchmark_bars`` 传入则复用（网格寻优预加载）；否则内部加载。
    基准/超额写入 ``metrics``，权益点追加 ``benchmark`` 字段供前端叠加。
    """
    equity = computed.get("equityCurve", [])
    if not equity:
        return
    actual_start = str(equity[0]["date"])[:10]
    actual_end = str(equity[-1]["date"])[:10]
    curve: dict[str, float] = {}
    label: str | None = None
    idx_bars = benchmark_bars if benchmark_bars is not None else load_benchmark(start, end)
    prior_index = [
        bar for bar in idx_bars if bar.date.isoformat()[:10] < actual_start
    ]
    aligned_index = [
        bar
        for bar in idx_bars
        if actual_start <= bar.date.isoformat()[:10] <= actual_end
    ]
    if aligned_index and aligned_index[0].close > 0:
        base = prior_index[-1].close if prior_index and prior_index[-1].close > 0 else aligned_index[0].close
        curve = {
            b.date.isoformat()[:10]: (b.close / base - 1) * 100
            for b in aligned_index
        }
        label = "沪深300"
    else:  # 降级：标的等权买入持有（衡量策略是否跑赢"躺平持有"）
        norm: dict[str, dict[str, float]] = {}
        for code, bars in bars_by_code.items():
            aligned = [
                bar
                for bar in bars
                if actual_start <= bar.date.isoformat()[:10] <= actual_end
            ]
            if aligned and aligned[0].close > 0:
                base = aligned[0].close
                norm[code] = {
                    b.date.isoformat()[:10]: (b.close / base - 1) * 100
                    for b in aligned
                }
        for d in {dd for mm in norm.values() for dd in mm}:
            vals = [norm[c][d] for c in norm if d in norm[c]]
            if vals:
                curve[d] = sum(vals) / len(vals)
        if curve:
            label = "买入持有"
    if not curve:
        return
    last_index_by_day: dict[str, int] = {}
    for index, point in enumerate(equity):
        last_index_by_day[str(point["date"])[:10]] = index
    last = 0.0
    for index, point in enumerate(equity):
        day = str(point["date"])[:10]
        # Daily benchmark closes are only known after that session closes.
        if index == last_index_by_day[day] and day in curve:
            last = curve[day]
        point["benchmark"] = round(last, 2)
    m = computed.get("metrics", {})
    m["benchmarkLabel"] = label
    m["benchmarkReturnPercent"] = round(last, 2)
    m["excessReturnPercent"] = round(m.get("totalReturnPercent", 0.0) - last, 2)
