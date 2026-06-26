"""回测运行编排 + 持久化（Phase 4 M3）。

同步跑回测（秒级）→ 落库 BacktestRun → 返回对齐前端的结果；并提供历史列表/详情、
内置策略目录（供前端选择与参数表单渲染）。
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.backtest.base import BacktestConfig
from app.backtest.runner import run_backtest
from app.backtest.strategies import STRATEGY_REGISTRY
from app.db.session import SessionLocal
from app.models.backtest import BacktestRun

# 内置策略目录：type / 名称 / 说明 / 参数 schema（前端按 schema 渲染表单）
_STRATEGY_CATALOG = [
    {
        "type": "dual_ma",
        "name": "双均线",
        "description": "快线上穿慢线建仓、下穿清仓（趋势跟随）",
        "params": [
            {"key": "fast", "label": "快线周期", "type": "int", "default": 5, "min": 1, "max": 120},
            {"key": "slow", "label": "慢线周期", "type": "int", "default": 20, "min": 2, "max": 250},
            {"key": "target", "label": "目标仓位", "type": "float", "default": 0.95, "min": 0.1, "max": 1.0},
        ],
    },
]


def strategy_catalog() -> list[dict]:
    return [c for c in _STRATEGY_CATALOG if c["type"] in STRATEGY_REGISTRY]


def _loads(s: str | None, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return default


def _to_dict(row: BacktestRun, with_detail: bool = False) -> dict:
    out = {
        "id": row.id,
        "strategyType": row.strategy_type,
        "status": row.status,
        "engine": row.engine,
        "error": row.error,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "config": _loads(row.config_json, {}),
        "metrics": _loads(row.metrics_json, {}),
    }
    if with_detail:
        out["equityCurve"] = _loads(row.equity_json, [])
        out["trades"] = _loads(row.trades_json, [])
        out["dataQuality"] = _loads(row.data_quality_json, {})
    return out


def run_and_save(user_id: str, req) -> dict:
    cfg = BacktestConfig(
        strategy_type=req.strategyType,
        params=req.params or {},
        codes=[c.strip() for c in req.codes if c and c.strip()],
        start=req.start,
        end=req.end,
        initial_capital=req.initialCapital,
        slippage=req.slippage,
        engine=req.engine or "native",
    )
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
    }
    with SessionLocal() as session:
        row = BacktestRun(
            id=run_id,
            user_id=user_id,
            strategy_type=cfg.strategy_type,
            status=status,
            config_json=json.dumps(config_dict, ensure_ascii=False),
            metrics_json=json.dumps(out.get("metrics") or {}, ensure_ascii=False, default=str),
            equity_json=json.dumps(out.get("equityCurve") or [], ensure_ascii=False, default=str),
            trades_json=json.dumps(out.get("trades") or [], ensure_ascii=False, default=str),
            data_quality_json=json.dumps(out.get("dataQuality") or {}, ensure_ascii=False),
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
