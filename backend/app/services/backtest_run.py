"""回测运行编排 + 持久化（Phase 4 M3）。

同步跑回测（秒级）→ 落库 BacktestRun → 返回对齐前端的结果；并提供历史列表/详情、
内置策略目录（供前端选择与参数表单渲染）。
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
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
from app.models.job import BacktestJob, BacktestJobStatus

# 网格寻优组合数上限（schema 会在运行前整体拒绝超限网格）
_MAX_GRID_COMBOS = 64
# 排名：回撤越小越好（升序），其余指标越大越好（降序）
_ASC_METRICS = {"maxDrawdownPercent"}
_DAILY_ONLY_STRATEGIES = {
    "donchian_breakout",
    "xs_momentum",
    "zscore_reversion",
    "composite_mf",
}

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
    {
        "type": "donchian_breakout",
        "name": "唐奇安突破",
        "description": "收盘突破前 N 日通道高点建仓、跌破低点退出",
        "params": [
            {"key": "channel", "label": "通道周期", "type": "int", "default": 20, "min": 10, "max": 120},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "xs_momentum",
        "name": "截面动量",
        "description": "按过去 N 日收益排序并等权持有前若干标的",
        "params": [
            {"key": "lookback", "label": "回看天数", "type": "int", "default": 60, "min": 20, "max": 250},
            {"key": "topN", "label": "持仓数量", "type": "int", "default": 3, "min": 1, "max": 20},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "zscore_reversion",
        "name": "Z-Score 反转",
        "description": "价格偏离滚动均值达到阈值时建仓并在均值附近退出",
        "params": [
            {"key": "period", "label": "统计周期", "type": "int", "default": 20, "min": 5, "max": 120},
            {"key": "entryZ", "label": "入场 Z 值", "type": "float", "default": -2.0, "min": -4.0, "max": -0.5},
            {"key": "exitZ", "label": "退出 Z 值", "type": "float", "default": 0.0, "min": -1.0, "max": 2.0},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "composite_mf",
        "name": "价格量能多因子",
        "description": "截面组合动量、低波动和流动性因子；不冒充财务基本面",
        "params": [
            {"key": "lookback", "label": "回看天数", "type": "int", "default": 60, "min": 20, "max": 250},
            {"key": "topN", "label": "持仓数量", "type": "int", "default": 5, "min": 1, "max": 20},
            {"key": "wMom", "label": "动量权重", "type": "float", "default": 0.4, "min": 0.0, "max": 1.0},
            {"key": "wLowVol", "label": "低波权重", "type": "float", "default": 0.3, "min": 0.0, "max": 1.0},
            {"key": "wLiq", "label": "流动性权重", "type": "float", "default": 0.3, "min": 0.0, "max": 1.0},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "flow_surge",
        "name": "资金流连续增强",
        "description": "仅使用当日已可见的追加式资金流版本，缺日或陈旧即退出",
        "params": [
            {"key": "window", "label": "连续天数", "type": "int", "default": 3, "min": 1, "max": 10},
            {"key": "minRatio", "label": "最低主力净占比", "type": "float", "default": 5.0, "min": 0.0, "max": 50.0},
            _TARGET_PARAM,
        ],
    },
    {
        "type": "fundamental_quality",
        "name": "PIT 价值质量",
        "description": "按当时已披露的 BPS/价格与 ROE 截面排名",
        "params": [
            {"key": "topN", "label": "持仓数量", "type": "int", "default": 5, "min": 1, "max": 20},
            {"key": "wValue", "label": "价值权重", "type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
            {"key": "wQuality", "label": "质量权重", "type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
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
        "jobId": row.job_id,
        "strategyType": row.strategy_type,
        "strategyId": row.strategy_id,
        "strategyVersionId": row.strategy_version_id,
        "strategyVersion": row.strategy_version,
        "definitionSha256": row.definition_sha256,
        "status": status,
        "engine": row.engine,
        "error": error,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "config": None if "config_json" in corrupt_fields else config,
        "metrics": None if "metrics_json" in corrupt_fields else metrics,
        "actualRange": None if "config_json" in corrupt_fields else config.get("actualRange"),
        "ruleQuality": None if "config_json" in corrupt_fields else config.get("ruleQuality"),
        "executionQuality": (
            None
            if "config_json" in corrupt_fields
            else config.get("executionQuality")
        ),
        "universeQuality": (
            None
            if "config_json" in corrupt_fields
            else config.get("universeQuality")
        ),
    }
    if with_detail:
        out["equityCurve"] = None if "equity_json" in corrupt_fields else equity
        out["trades"] = None if "trades_json" in corrupt_fields else trades
        out["dataQuality"] = None if "data_quality_json" in corrupt_fields else data_quality
    return out


def _validated_run_request(req: Any):
    from app.schemas.backtest import RunBacktestRequest

    return RunBacktestRequest.model_validate(req, from_attributes=True)


def _bind_pit_membership(config: BacktestConfig) -> BacktestConfig:
    if config.universe_mode != "pit_filtered":
        return config
    from datetime import date

    from app.backtest.universe import expected_session_dates
    from app.services import universe_membership

    start = date.fromisoformat(config.start[:10])
    end = date.fromisoformat(config.end[:10])
    expected_dates = set(expected_session_dates(start, end))
    eligible_by_date = universe_membership.eligible_map(
        config.codes,
        start,
        end,
    )
    if not eligible_by_date:
        raise ValueError(
            "请求区间尚未物化 PIT 股票池，请先运行 build-pit-universe"
        )
    missing_dates = sorted(expected_dates - set(eligible_by_date))
    if missing_dates:
        raise ValueError(
            "PIT 股票池日期覆盖不完整，缺少 "
            f"{missing_dates[0]} 等 {len(missing_dates)} 日"
        )
    return replace(config, eligible_by_date=eligible_by_date)


def _config_from_run_request(
    req: Any, user_id: str
) -> tuple[BacktestConfig, dict[str, Any] | None]:
    validated = _validated_run_request(req)
    strategy_type = validated.strategyType
    strategy_params = validated.params
    provenance: dict[str, Any] | None = None
    if validated.strategyId is not None:
        from app.services import strategy as strategy_service

        version = strategy_service.get_version(
            user_id,
            validated.strategyId,
            validated.strategyVersion,
        )
        if version is None:
            raise ValueError("策略版本不存在或无权访问")
        if version["definitionType"] != "builtin":
            raise ValueError("自定义策略的版本化回测将在 M2 沙箱执行阶段开放")
        if version["protocolVersion"] != "signal-v1":
            raise ValueError("策略协议版本与当前回测执行器不兼容")
        if version["implementationVersion"] != "builtin-v1":
            raise ValueError("内置策略实现版本与当前回测执行器不兼容")
        strategy_type = version["builtinType"]
        strategy_params = version["params"]
        provenance = {
            "strategyId": validated.strategyId,
            "strategyVersion": validated.strategyVersion,
            "strategyVersionId": version["id"],
            "strategyDefinitionSha256": version["definitionSha256"],
            "strategyProtocolVersion": version["protocolVersion"],
            "strategyImplementationVersion": version[
                "implementationVersion"
            ],
        }
    if strategy_type in _DAILY_ONLY_STRATEGIES and validated.frequency != "1d":
        raise ValueError("固定策略版本按交易日定义，仅支持日线回测")
    config = BacktestConfig(
        strategy_type=strategy_type,
        params=strategy_params,
        codes=validated.codes,
        start=validated.start.isoformat(),
        end=validated.end.isoformat(),
        initial_capital=validated.initialCapital,
        slippage=validated.slippage,
        max_participation=validated.maxParticipation,
        engine=validated.engine,
        frequency=validated.frequency,
        universe_mode=validated.universeMode,
    )
    return _bind_pit_membership(config), provenance


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
            "maxParticipation": base_config.max_participation,
            "engine": base_config.engine,
            "frequency": base_config.frequency,
            "universeMode": base_config.universe_mode,
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
        max_participation=validated.maxParticipation,
        engine=validated.engine,
        frequency=validated.frequency,
        universe_mode=validated.universeMode,
    )
    return config, validated.paramGrid, validated.sortBy


def run_and_save(user_id: str, req) -> dict:
    cfg, provenance = _config_from_run_request(req, user_id)
    out = run_backtest(cfg)
    return _save_run(user_id, cfg, out, provenance)


def _save_run(
    user_id: str,
    cfg: BacktestConfig,
    out: dict,
    provenance: dict[str, Any] | None,
    *,
    job_id: str | None = None,
    claim_token: str | None = None,
) -> dict:
    run_id = uuid4().hex
    status = "failed" if out.get("error") else "completed"
    membership_snapshot = {
        day: list(codes)
        for day, codes in sorted(cfg.eligible_by_date.items())
    }
    membership_sha256 = (
        hashlib.sha256(
            json.dumps(
                membership_snapshot,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if membership_snapshot
        else None
    )
    config_dict = {
        "strategyType": cfg.strategy_type,
        "params": cfg.params,
        "codes": cfg.codes,
        "start": cfg.start,
        "end": cfg.end,
        "initialCapital": cfg.initial_capital,
        "slippage": cfg.slippage,
        "maxParticipation": cfg.max_participation,
        "engine": cfg.engine,
        "frequency": cfg.frequency,
        "universeMode": cfg.universe_mode,
        "universeMembership": membership_snapshot or None,
        "universeMembershipSha256": membership_sha256,
        "actualRange": out.get("actualRange"),
        "ruleQuality": out.get("ruleQuality"),
        "executionQuality": out.get("executionQuality"),
        "universeQuality": out.get("universeQuality"),
        **(provenance or {}),
    }
    with SessionLocal() as session:
        job: BacktestJob | None = None
        if job_id is not None:
            job = session.execute(
                select(BacktestJob)
                .where(
                    BacktestJob.id == job_id,
                    BacktestJob.claim_token == claim_token,
                    BacktestJob.status == BacktestJobStatus.RUNNING,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if job is None or job.cancel_requested:
                session.rollback()
                return {"cancelled": True}
        row = BacktestRun(
            id=run_id,
            user_id=user_id,
            job_id=job_id,
            strategy_type=cfg.strategy_type,
            strategy_id=(
                provenance.get("strategyId") if provenance else None
            ),
            strategy_version_id=(
                provenance.get("strategyVersionId") if provenance else None
            ),
            strategy_version=(
                provenance.get("strategyVersion") if provenance else None
            ),
            definition_sha256=(
                provenance.get("strategyDefinitionSha256")
                if provenance
                else None
            ),
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
        if job is not None:
            session.flush()
            serialized = _to_dict(row, with_detail=True)
            job.status = BacktestJobStatus.COMPLETED
            job.result_json = dump_envelope(serialized)
            job.finished_at = datetime.now(UTC)
            job.updated_at = job.finished_at
        session.commit()
        return (
            serialized
            if job is not None
            else _to_dict(row, with_detail=True)
        )


def run_full_a_and_save(
    user_id: str,
    req: Any,
    *,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    job_id: str | None = None,
    claim_token: str | None = None,
) -> dict:
    from app.backtest.full_a import run_chunked
    from app.schemas.backtest import FullABacktestRequest
    from app.services import strategy as strategy_service

    if job_id is not None:
        with SessionLocal() as session:
            existing = session.execute(
                select(BacktestRun).where(
                    BacktestRun.job_id == job_id,
                    BacktestRun.user_id == user_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _to_dict(existing, with_detail=True)
    validated = FullABacktestRequest.model_validate(req, from_attributes=True)
    strategy_type = validated.strategyType
    strategy_params = validated.params
    provenance: dict[str, Any] | None = None
    if validated.strategyId is not None:
        version = strategy_service.get_version(
            user_id,
            validated.strategyId,
            validated.strategyVersion,
        )
        if version is None:
            raise ValueError("策略版本不存在或无权访问")
        if version["definitionType"] != "builtin":
            raise ValueError("全 A 回测不执行自定义 Python 策略")
        if version["builtinType"] not in _DAILY_ONLY_STRATEGIES:
            raise ValueError("策略版本不属于全 A 截面策略")
        if version["builtinType"] not in {"xs_momentum", "composite_mf"}:
            raise ValueError("全 A 回测仅支持截面动量或价格量能多因子")
        if version["protocolVersion"] != "signal-v1":
            raise ValueError("策略协议版本与当前回测执行器不兼容")
        if version["implementationVersion"] != "builtin-v1":
            raise ValueError("内置策略实现版本与当前回测执行器不兼容")
        strategy_type = version["builtinType"]
        strategy_params = version["params"]
        provenance = {
            "strategyId": validated.strategyId,
            "strategyVersion": validated.strategyVersion,
            "strategyVersionId": version["id"],
            "strategyDefinitionSha256": version["definitionSha256"],
            "strategyProtocolVersion": version["protocolVersion"],
            "strategyImplementationVersion": version[
                "implementationVersion"
            ],
        }
    config = BacktestConfig(
        strategy_type=strategy_type,
        params=strategy_params,
        codes=[],
        start=validated.start.isoformat(),
        end=validated.end.isoformat(),
        initial_capital=validated.initialCapital,
        slippage=validated.slippage,
        max_participation=validated.maxParticipation,
        engine="native",
        frequency="1d",
        universe_mode="full_a_pit",
    )
    result = run_chunked(
        config,
        cancel_check=cancel_check,
        on_progress=on_progress,
    )
    if result.get("cancelled"):
        return result
    if cancel_check and cancel_check():
        return {
            "cancelled": True,
            "progressDone": len(result.get("equityCurve", [])),
            "progressTotal": len(result.get("equityCurve", [])),
        }
    saved = _save_run(
        user_id,
        config,
        result,
        provenance,
        job_id=job_id,
        claim_token=claim_token,
    )
    if saved.get("cancelled"):
        return saved
    return {**saved, "_jobFinalized": job_id is not None}


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
    *,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    """参数网格搜索：对参数笛卡尔积逐组回测，按 ``sort_by`` 排名。

    **只加载一次行情与基准**，对每组参数复用（``runner.run_on_bars``）。
    所有组合会在加载行情前整体校验，非法或超限网格不会部分执行。
    ``cancel_check`` 为真时中止并返回 ``cancelled=True``（H21）。
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
        max_participation=validated.maxParticipation,
        engine=validated.engine,
        frequency=validated.frequency,
        universe_mode=validated.universeMode,
    )
    base_config = _bind_pit_membership(base_config)
    param_grid = validated.paramGrid
    sort_by = validated.sortBy
    keys = [k for k in param_grid if param_grid[k]]
    combos = list(itertools.product(*[param_grid[k] for k in keys])) if keys else []
    total = len(combos)
    if on_progress:
        on_progress(0, total)

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
    for i, combo in enumerate(combos):
        if cancel_check and cancel_check():
            return {
                "results": results,
                "best": None,
                "engine": base_config.engine,
                "sortBy": sort_by,
                "truncated": True,
                "cancelled": True,
                "dataQuality": result_quality,
                "actualRange": actual_range,
                "ruleQuality": rule_quality,
                "progressDone": i,
                "progressTotal": total,
            }
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
        if on_progress:
            on_progress(i + 1, total)

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
