"""Server-owned M3 regime, forecast, account, industry, and risk orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.backtest.data import (
    _ingestion_run_quality_in_session,
    _load_hfq_bars_in_session,
)
from app.core.json_payload import dump_envelope
from app.db.session import SessionLocal
from app.models.prediction import (
    PortfolioAllocationDecision,
    PortfolioRiskProfile,
    RegimeSnapshot,
)
from app.models.universe import UniverseSnapshotDaily
from app.prediction.portfolio import StrategyProposal, allocate_portfolio
from app.prediction.regime import classify_market_regime
from app.services import (
    industry_history,
    prediction_registry,
    trading,
    universe_membership,
)

CAPITAL_LIMIT = 200_000.0
LEVERAGE_LIMIT = 200_000.0


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _authoritative_regime(session, as_of: date) -> dict[str, Any]:
    start = (as_of - timedelta(days=120)).isoformat()
    end = as_of.isoformat()
    benchmark, quality = _load_hfq_bars_in_session(
        session,
        "000300.SH",
        start,
        end,
    )
    ingestion_quality = _ingestion_run_quality_in_session(
        session,
        "000300.SH",
        start,
        end,
        "1d",
        actual_start=benchmark[0].date if benchmark else None,
        actual_end=benchmark[-1].date if benchmark else None,
    )
    if ingestion_quality is not None:
        quality = ingestion_quality
    if quality != "full":
        raise ValueError("沪深300基准数据或复权质量不完整")
    bars = [bar for bar in benchmark if bar.date <= as_of]
    if len(bars) < 60 or bars[-1].date != as_of:
        raise ValueError("沪深300缺少截至决策日的 60 日完整窗口")
    snapshot = session.get(
        UniverseSnapshotDaily,
        {
            "trade_date": as_of,
            "rules_version": universe_membership.RULES_VERSION,
        },
    )
    if (
        snapshot is None
        or snapshot.advancing_count is None
        or snapshot.declining_count is None
        or snapshot.advancing_count + snapshot.declining_count <= 0
    ):
        raise ValueError("决策日缺少可信市场涨跌宽度")
    breadth = snapshot.advancing_count / (
        snapshot.advancing_count + snapshot.declining_count
    )
    result = classify_market_regime(
        index_closes=[bar.close for bar in bars[-60:]],
        market_breadth=breadth,
    )
    return {
        **result,
        "asOf": as_of.isoformat(),
        "benchmarkQuality": quality,
        "universeMembershipSha256": snapshot.membership_sha256,
    }


def _risk_profile(
    session, user_id: str, total_assets: float
) -> PortfolioRiskProfile:
    insert = (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert
    )
    session.execute(
        insert(PortfolioRiskProfile)
        .values(
            user_id=user_id,
            capital_limit=CAPITAL_LIMIT,
            leverage_limit=LEVERAGE_LIMIT,
            high_water_mark=max(total_assets, CAPITAL_LIMIT),
            kill_switch_active=False,
        )
        .on_conflict_do_nothing(
            index_elements=[PortfolioRiskProfile.user_id]
        )
    )
    row = session.execute(
        select(PortfolioRiskProfile)
        .where(PortfolioRiskProfile.user_id == user_id)
        .with_for_update()
    ).scalar_one()
    if total_assets > row.high_water_mark:
        row.high_water_mark = total_assets
    session.flush()
    return row


def preview(
    user_id: str,
    *,
    requested_codes: list[str],
    as_of: date,
) -> dict[str, Any]:
    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
        latest_snapshot_date = session.scalar(
            select(func.max(UniverseSnapshotDaily.trade_date)).where(
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION
            )
        )
        if latest_snapshot_date != as_of:
            raise ValueError("权威组合预览仅允许最新已物化交易日")
        account, positions = trading.get_portfolio_snapshot_in_session(
            session, user_id, valuation_date=as_of
        )
        codes = sorted(
            set(requested_codes)
            | {str(position["code"]) for position in positions}
        )
        if not codes:
            raise ValueError("至少需要一个候选或持仓标的")
        if len(codes) > 20:
            raise ValueError("权威组合预览最多处理 20 个候选和持仓标的")
        industries = industry_history.industries_asof_in_session(
            session, codes, as_of
        )
        predictions = []
        for code in codes:
            prediction = prediction_registry.get_prediction_in_session(
                session, code, as_of=as_of
            )
            if (
                prediction is None
                or prediction["signalDate"] != as_of.isoformat()
            ):
                raise ValueError(f"{code} 缺少决策日 Champion 预测")
            predictions.append(prediction)
        model_run_ids = {
            prediction["model"]["runId"] for prediction in predictions
        }
        if len(model_run_ids) != 1:
            raise ValueError("候选预测未绑定同一个 Champion")
        regime = _authoritative_regime(session, as_of)
        profile = _risk_profile(
            session, user_id, float(account["totalAssets"])
        )
        drawdown = max(
            0.0,
            (
                profile.high_water_mark - float(account["totalAssets"])
            )
            / profile.high_water_mark,
        )
        current_weights = {
            position["code"]: float(position["marketValue"])
            / profile.capital_limit
            for position in positions
        }
        targets = {}
        predicted_losses = {}
        for prediction in predictions:
            interval = prediction["returnInterval80"]
            confidence = max(
                0.0, (float(prediction["probabilityUp"]) - 0.5) * 2
            )
            targets[prediction["code"]] = (
                confidence if float(interval["median"]) > 0 else 0.0
            )
            predicted_losses[prediction["code"]] = max(
                0.0, -float(interval["low"])
            )
        model_run_id = next(iter(model_run_ids))
        proposal = StrategyProposal(
            strategy_id=f"champion:{model_run_id}",
            category="multi_factor",
            confidence=1.0,
            target_weights=targets,
        )
        max_gross = 1 + profile.leverage_limit / profile.capital_limit
        allocation = allocate_portfolio(
            proposals=[proposal],
            regime=regime["regime"],
            equity=profile.capital_limit,
            industries=industries,
            predicted_loss_rates=predicted_losses,
            current_weights=current_weights,
            drawdown=0.20 if profile.kill_switch_active else drawdown,
            max_gross_exposure=max_gross,
        )
        inputs = {
            "asOf": as_of.isoformat(),
            "account": account,
            "positions": positions,
            "riskProfile": {
                "capitalLimit": profile.capital_limit,
                "leverageLimit": profile.leverage_limit,
                "highWaterMark": profile.high_water_mark,
                "killSwitchActive": profile.kill_switch_active,
            },
            "industries": industries,
            "predictions": predictions,
            "regime": regime,
        }
        regime_id = str(uuid4())
        decision_id = str(uuid4())
        session.add(
            RegimeSnapshot(
                id=regime_id,
                user_id=user_id,
                user_id_snapshot=user_id,
                as_of=as_of,
                regime=regime["regime"],
                rules_version=regime["rulesVersion"],
                input_sha256=_hash(regime),
                payload_json=dump_envelope(regime),
            )
        )
        output = {
            **allocation,
            "authoritative": True,
            "executionApproved": False,
            "notice": "仅生成服务端权威组合目标；订单执行审批在 M5 开放",
        }
        session.add(
            PortfolioAllocationDecision(
                id=decision_id,
                user_id=user_id,
                user_id_snapshot=user_id,
                regime_snapshot_id=regime_id,
                model_run_id=model_run_id,
                as_of=as_of,
                input_sha256=_hash(inputs),
                output_sha256=_hash(output),
                risk_state=allocation["riskState"],
                payload_json=dump_envelope(
                    {"input": inputs, "output": output}
                ),
            )
        )
        session.commit()
        return {
            "decisionId": decision_id,
            "regimeSnapshotId": regime_id,
            "modelRunId": model_run_id,
            **output,
        }
