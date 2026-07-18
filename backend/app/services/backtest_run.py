"""回测运行编排 + 持久化（Phase 4 M3）。

同步跑回测（秒级）→ 落库 BacktestRun → 返回对齐前端的结果；并提供历史列表/详情、
内置策略目录（供前端选择与参数表单渲染）。
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.backtest import runner
from app.backtest.base import BacktestConfig
from app.backtest.runner import run_backtest
from app.backtest.strategies import STRATEGY_REGISTRY
from app.core.json_payload import JsonCorruptError, dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.backtest import BacktestRun

# 网格寻优组合数上限（schema 会在运行前整体拒绝超限网格）
_MAX_GRID_COMBOS = 64
# 排名：回撤越小越好（升序），其余指标越大越好（降序）
_ASC_METRICS = {"maxDrawdownPercent"}

# 内置策略目录：type / 名称 / 说明 / 参数 schema（前端按 schema 渲染表单）
_TARGET_PARAM = {"key": "target", "label": "目标仓位", "type": "float", "default": 0.95, "min": 0.1, "max": 1.0}

_STRATEGY_CATALOG = [
    {
        "type": "dual_ma",
        "name": "双均线",
        "description": "快线上穿慢线建仓、下穿清仓（趋势跟随）",
        "params": [
            {"key": "fast", "label": "快线周期", "type": "int", "default": 5, "min": 1, "max": 120},
            {"key": "slow", "label": "慢线周期", "type": "int", "default": 20, "min": 2, "max": 250},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "rsi",
        "name": "RSI 反转",
        "description": "RSI 超卖买入、超买清仓（均值回归）",
        "params": [
            {"key": "period", "label": "RSI 周期", "type": "int", "default": 14, "min": 2, "max": 60},
            {"key": "low", "label": "超卖阈值", "type": "float", "default": 30, "min": 5, "max": 50},
            {"key": "high", "label": "超买阈值", "type": "float", "default": 70, "min": 50, "max": 95},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "boll",
        "name": "布林带",
        "description": "价格触下轨买入、触上轨清仓（均值回归）",
        "params": [
            {"key": "period", "label": "周期", "type": "int", "default": 20, "min": 2, "max": 120},
            {"key": "k", "label": "标准差倍数", "type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "momentum",
        "name": "动量",
        "description": "过去 N 日收益为正则持有、为负则清仓（趋势延续）",
        "params": [
            {"key": "lookback", "label": "回看天数", "type": "int", "default": 20, "min": 1, "max": 250},
            _TARGET_PARAM,
        ],
    },
]


def strategy_catalog() -> list[dict]:
    return [c for c in _STRATEGY_CATALOG if c["type"] in STRATEGY_REGISTRY]


def _load_field(raw: Any, *, expect: str, field: str, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    return load_envelope(raw, expect=expect, field=field)  # type: ignore[arg-type]


def _to_dict(row: BacktestRun, with_detail: bool = False) -> dict:
    corrupt_fields: list[str] = []
    config: dict = {}
    metrics: dict = {}
    equity: list = []
    trades: list = []
    data_quality: dict = {}

    try:
        config = _load_field(row.config_json, expect="dict", field="config_json", default={})
        if not isinstance(config, dict):
            raise JsonCorruptError("config must be object", field="config_json")
    except JsonCorruptError:
        corrupt_fields.append("config_json")
        config = {}

    try:
        metrics = _load_field(row.metrics_json, expect="dict", field="metrics_json", default={})
        if not isinstance(metrics, dict):
            raise JsonCorruptError("metrics must be object", field="metrics_json")
    except JsonCorruptError:
        corrupt_fields.append("metrics_json")
        metrics = {}

    if with_detail:
        try:
            equity = _load_field(row.equity_json, expect="list", field="equity_json", default=[])
        except JsonCorruptError:
            corrupt_fields.append("equity_json")
            equity = []
        try:
            trades = _load_field(row.trades_json, expect="list", field="trades_json", default=[])
        except JsonCorruptError:
            corrupt_fields.append("trades_json")
            trades = []
        try:
            data_quality = _load_field(
                row.data_quality_json, expect="dict", field="data_quality_json", default={}
            )
        except JsonCorruptError:
            corrupt_fields.append("data_quality_json")
            data_quality = {}

    status = row.status
    error = row.error
    if corrupt_fields:
        status = "data_corrupt"
        error = f"corrupt JSON fields: {', '.join(corrupt_fields)}"

    out = {
        "id": row.id,
        "strategyType": row.strategy_type,
        "status": status,
        "engine": row.engine,
        "error": error,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "config": None if "config_json" in corrupt_fields else config,
        "metrics": None if "metrics_json" in corrupt_fields else metrics,
        "actualRange": None if "config_json" in corrupt_fields else config.get("actualRange"),
        "ruleQuality": None if "config_json" in corrupt_fields else config.get("ruleQuality"),
    }
    if with_detail:
        out["equityCurve"] = None if "equity_json" in corrupt_fields else equity
        out["trades"] = None if "trades_json" in corrupt_fields else trades
        out["dataQuality"] = None if "data_quality_json" in corrupt_fields else data_quality
    return out


def _validated_run_request(req: Any):
    from app.schemas.backtest import RunBacktestRequest

    return RunBacktestRequest.model_validate(req, from_attributes=True)


def _config_from_run_request(req: Any) -> BacktestConfig:
    validated = _validated_run_request(req)
    return BacktestConfig(
        strategy_type=validated.strategyType,
        params=validated.params,
        codes=validated.codes,
        start=validated.start.isoformat(),
        end=validated.end.isoformat(),
        initial_capital=validated.initialCapital,
        slippage=validated.slippage,
        engine=validated.engine,
        frequency=validated.frequency,
    )


def _validated_grid_request(
    base_config: BacktestConfig,
    param_grid: dict[str, list],
    sort_by: str,
):
    from app.schemas.backtest import GridSearchRequest
    from app.services.strategy import validate_params

    _, base_params = validate_params(base_config.strategy_type, base_config.params)
    effective_grid = {
        key: [value]
        for key, value in base_params.items()
        if key not in param_grid
    }
    effective_grid.update(param_grid)
    validated = GridSearchRequest.model_validate(
        {
            "strategyType": base_config.strategy_type,
            "paramGrid": effective_grid,
            "codes": base_config.codes,
            "start": base_config.start,
            "end": base_config.end,
            "initialCapital": base_config.initial_capital,
            "slippage": base_config.slippage,
            "engine": base_config.engine,
            "frequency": base_config.frequency,
            "sortBy": sort_by,
        }
    )
    validated.paramGrid = {
        key: validated.paramGrid[key]
        for key in param_grid
    }
    return validated, base_params


def config_from_grid_request(req: Any) -> tuple[BacktestConfig, dict[str, list], str]:
    from app.schemas.backtest import GridSearchRequest

    validated = GridSearchRequest.model_validate(req, from_attributes=True)
    config = BacktestConfig(
        strategy_type=validated.strategyType,
        params={},
        codes=validated.codes,
        start=validated.start.isoformat(),
        end=validated.end.isoformat(),
        initial_capital=validated.initialCapital,
        slippage=validated.slippage,
        engine=validated.engine,
        frequency=validated.frequency,
    )
    return config, validated.paramGrid, validated.sortBy


def run_and_save(user_id: str, req) -> dict:
    cfg = _config_from_run_request(req)
    out = run_backtest(cfg)
    run_id = uuid4().hex
    status = "failed" if out.get("error") else "completed"
    config_dict = {
        "strategyType": cfg.strategy_type,
        "params": cfg.params,
        "codes": cfg.codes,
        "start": cfg.start,
        "end": cfg.end,
        "initialCapital": cfg.initial_capital,
        "slippage": cfg.slippage,
        "engine": cfg.engine,
        "frequency": cfg.frequency,
        "actualRange": out.get("actualRange"),
        "ruleQuality": out.get("ruleQuality"),
    }
    with SessionLocal() as session:
        row = BacktestRun(
            id=run_id,
            user_id=user_id,
            strategy_type=cfg.strategy_type,
            status=status,
            config_json=dump_envelope(config_dict),
            metrics_json=dump_envelope(out.get("metrics") or {}),
            equity_json=dump_envelope(out.get("equityCurve") or []),
            trades_json=dump_envelope(out.get("trades") or []),
            data_quality_json=dump_envelope(out.get("dataQuality") or {}),
            engine=out.get("engine") or cfg.engine,
            error=out.get("error"),
        )
        session.add(row)
        session.commit()
        return _to_dict(row, with_detail=True)


def list_runs(user_id: str, limit: int = 20) -> list[dict]:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(BacktestRun)
                .where(BacktestRun.user_id == user_id)
                .order_by(BacktestRun.created_at.desc())
                .limit(limit)
            ).scalars().all()
        )
        return [_to_dict(r) for r in rows]


def get_run(user_id: str, run_id: str) -> dict | None:
    with SessionLocal() as session:
        row = session.get(BacktestRun, run_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_dict(row, with_detail=True)


def build_review_input(user_id: str, run_id: str) -> str | None:
    """把回测结果汇总成给 LLM 的诊断输入文本（只喂真实数据）。无此回测返回 None。"""
    run = get_run(user_id, run_id)
    if run is None:
        return None
    if run.get("status") == "data_corrupt":
        return None
    m = run.get("metrics") or {}
    cfg = run.get("config") or {}
    if not isinstance(m, dict) or not isinstance(cfg, dict):
        return None
    actual = run.get("actualRange") or cfg.get("actualRange") or {}
    lines = ["【回测结果汇总】"]
    lines.append(
        f"策略 {cfg.get('strategyType')}｜参数 {cfg.get('params')}｜标的 {cfg.get('codes')}｜"
        f"周期 {cfg.get('frequency', '1d')}｜请求区间 {cfg.get('start')}~{cfg.get('end')}｜"
        f"实际区间 {actual.get('start', '暂无')}~{actual.get('end', '暂无')}｜"
        f"初始资金 {cfg.get('initialCapital')}｜滑点 {cfg.get('slippage')}"
    )
    lines.append(
        f"总收益 {m.get('totalReturnPercent')}%｜年化 {m.get('annualReturnPercent')}%｜"
        f"夏普 {m.get('sharpeRatio')}｜最大回撤 {m.get('maxDrawdownPercent')}%"
    )
    lines.append(f"胜率 {m.get('winRate')}%｜盈亏比 {m.get('profitFactor')}｜交易回合 {m.get('totalTrades')}")
    lines.append(
        f"基准（{m.get('benchmarkLabel')}）{m.get('benchmarkReturnPercent')}%｜超额 {m.get('excessReturnPercent')}%"
    )
    trades = run.get("trades") or []
    if trades:
        lines.append("\n近期成交回合（最多 10）：")
        for t in trades[:10]:
            lines.append(
                f"- {t.get('symbol')} {t.get('entryTime')}买@{t.get('entryPrice')} → "
                f"{t.get('exitTime')}卖@{t.get('exitPrice')} 收益 {t.get('returnPercent')}%"
            )
    lines.append("\n请基于以上真实回测数据做诊断。")
    return "\n".join(lines)


def grid_search(
    base_config: BacktestConfig,
    param_grid: dict[str, list],
    sort_by: str = "sharpeRatio",
) -> dict:
    """参数网格搜索：对参数笛卡尔积逐组回测，按 ``sort_by`` 排名。

    **只加载一次行情与基准**，对每组参数复用（``runner.run_on_bars``）。
    所有组合会在加载行情前整体校验，非法或超限网格不会部分执行。
    """
    validated, base_params = _validated_grid_request(
        base_config,
        param_grid,
        sort_by,
    )
    from app.services.strategy import validate_params

    keys = list(validated.paramGrid)
    for combo in itertools.product(*(validated.paramGrid[key] for key in keys)):
        validate_params(
            validated.strategyType,
            {**base_params, **dict(zip(keys, combo, strict=True))},
        )
    base_config = BacktestConfig(
        strategy_type=validated.strategyType,
        params=base_params,
        codes=validated.codes,
        start=validated.start.isoformat(),
        end=validated.end.isoformat(),
        initial_capital=validated.initialCapital,
        slippage=validated.slippage,
        engine=validated.engine,
        frequency=validated.frequency,
    )
    param_grid = validated.paramGrid
    sort_by = validated.sortBy
    keys = [k for k in param_grid if param_grid[k]]
    combos = list(itertools.product(*[param_grid[k] for k in keys])) if keys else []

    bars_by_code, data_quality = runner.load_bars(base_config)
    missing = runner.unusable_data_codes(base_config, bars_by_code, data_quality)
    if missing:
        return {
            "results": [],
            "best": None,
            "engine": base_config.engine,
            "dataQuality": data_quality,
            "error": runner.missing_data_error(base_config, missing, data_quality),
        }
    benchmark_bars, benchmark_quality = runner.load_benchmark_with_quality(
        base_config.start,
        base_config.end,
    )
    benchmark_key = "000300.SH:benchmark"
    result_quality = {**data_quality, benchmark_key: benchmark_quality}
    if benchmark_quality in {"invalid_ohlc", "partial_ingestion"}:
        return {
            "results": [],
            "best": None,
            "engine": base_config.engine,
            "dataQuality": result_quality,
            "error": "沪深300基准数据不可信，已拒绝回测",
        }

    results: list[dict] = []
    actual_range = None
    rule_quality = None
    for combo in combos:
        params = {**base_config.params, **dict(zip(keys, combo, strict=True))}
        cfg = replace(base_config, params=params)
        out = runner.run_on_bars(
            cfg,
            bars_by_code,
            data_quality,
            benchmark_bars,
            benchmark_quality,
        )
        if out.get("error"):
            return {
                "results": [],
                "best": None,
                "engine": base_config.engine,
                "dataQuality": result_quality,
                "error": out["error"],
            }
        actual_range = out.get("actualRange")
        rule_quality = out.get("ruleQuality")
        m = out.get("metrics", {})
        results.append(
            {
                "params": dict(zip(keys, combo, strict=True)),
                "metrics": {
                    "totalReturnPercent": m.get("totalReturnPercent"),
                    "annualReturnPercent": m.get("annualReturnPercent"),
                    "sharpeRatio": m.get("sharpeRatio"),
                    "maxDrawdownPercent": m.get("maxDrawdownPercent"),
                    "winRate": m.get("winRate"),
                    "totalTrades": m.get("totalTrades"),
                    "excessReturnPercent": m.get("excessReturnPercent"),
                },
            }
        )

    reverse = sort_by not in _ASC_METRICS
    inf = float("-inf") if reverse else float("inf")
    results.sort(key=lambda r: r["metrics"].get(sort_by) if r["metrics"].get(sort_by) is not None else inf, reverse=reverse)
    return {
        "results": results,
        "best": results[0] if results else None,
        "engine": base_config.engine,
        "sortBy": sort_by,
        "truncated": False,
        "dataQuality": result_quality,
        "actualRange": actual_range,
        "ruleQuality": rule_quality,
    }
