"""Server-derived Champion-Challenger paper and shadow evaluation."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import UTC, date, datetime, timedelta
from statistics import mean, stdev
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.backtest import runner
from app.backtest.universe import expected_session_dates
from app.core.config import settings
from app.core.json_payload import dump_envelope, load_envelope
from app.db.session import SessionLocal
from app.models.decision import DecisionRun
from app.models.evolution import (
    BehaviorAttribution,
    BehaviorAttributionAttempt,
    EvolutionObservation,
    EvolutionProgram,
    EvolutionSignalCommitment,
    EvolutionTransition,
)
from app.models.prediction import (
    PortfolioAllocationDecision,
    PredictionForecast,
    PredictionModelRun,
)
from app.models.room import DecisionOverride
from app.models.universe import UniverseSnapshotDaily
from app.prediction.portfolio import StrategyProposal, allocate_portfolio
from app.services import (
    authoritative_allocation,
    industry_history,
    prediction_registry,
    prediction_training,
    universe_membership,
)
from app.services.trading_rules import commission, stamp_tax

INITIAL_EQUITY = 200_000.0
SIMULATION_SESSIONS = 60
SHADOW_SESSIONS = 20
CLAIM_LEASE = timedelta(minutes=10)


class EvolutionConflictError(ValueError):
    pass


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _attestation_key(key_id: str) -> str:
    if key_id == settings.evolution_attestation_key_id:
        return settings.evolution_attestation_key
    previous = dict(
        item.strip().split("=", 1)
        for item in settings.evolution_attestation_previous_keys.split(",")
        if "=" in item.strip()
    )
    key = previous.get(key_id)
    if not key:
        raise ValueError("M6 attestation key ID 不可用")
    return key


def _attest(
    kind: str,
    evidence_sha256: str,
    context: Any,
    *,
    key_id: str,
) -> str:
    message = _hash(
        {
            "domain": "evolution-attestation-v1",
            "kind": kind,
            "evidenceSha256": evidence_sha256,
            "context": context,
        }
    )
    return hmac.new(
        _attestation_key(key_id).encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _next_session(day: date) -> date:
    sessions = expected_session_dates(
        day + timedelta(days=1), day + timedelta(days=10)
    )
    if not sessions:
        raise ValueError("无法确定下一交易日")
    return sessions[0]


def _transition(
    session,
    program: EvolutionProgram,
    *,
    to_stage: str,
    reason: str,
    metrics: dict[str, Any],
    as_of: date,
) -> None:
    previous = session.execute(
        select(EvolutionTransition)
        .where(EvolutionTransition.program_id == program.id)
        .order_by(EvolutionTransition.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()
    sequence = (previous.sequence if previous else 0) + 1
    evidence = {
        "programId": program.id,
        "sequence": sequence,
        "from": program.stage,
        "to": to_stage,
        "reason": reason,
        "metrics": metrics,
        "asOf": as_of.isoformat(),
        "previousTransitionSha256": (
            previous.evidence_sha256 if previous else None
        ),
    }
    evidence_sha256 = _hash(evidence)
    session.add(
        EvolutionTransition(
            id=str(uuid4()),
            program_id=program.id,
            sequence=sequence,
            from_stage=program.stage,
            to_stage=to_stage,
            reason=reason,
            metrics_sha256=_hash(metrics),
            evidence_sha256=evidence_sha256,
            previous_transition_sha256=(
                previous.evidence_sha256 if previous else None
            ),
            attestation_sha256=_attest(
                "transition",
                evidence_sha256,
                {
                    "programId": program.id,
                    "sequence": sequence,
                },
                key_id=program.attestation_key_id,
            ),
            payload_json=dump_envelope(evidence),
        )
    )
    program.stage = to_stage
    program.stage_started_on = as_of


def enroll(
    model_run_id: str,
    *,
    codes: list[str],
    created_by_user_id: str,
) -> dict[str, Any]:
    if not 1 <= len(codes) <= 20 or len(set(codes)) != len(codes):
        raise ValueError("Challenger 标的必须为 1–20 个不重复代码")
    with SessionLocal.begin() as session:
        model = session.execute(
            select(PredictionModelRun)
            .where(PredictionModelRun.id == model_run_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            model is None
            or model.status != "validated"
            or model.is_champion
            or not model.artifact_sha256
        ):
            raise ValueError("仅可信 validated 非 Champion 模型可进入模拟")
        existing = session.execute(
            select(EvolutionProgram).where(
                EvolutionProgram.model_run_id == model_run_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _summary(existing)
        latest = session.scalar(
            select(func.max(UniverseSnapshotDaily.trade_date)).where(
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION
            )
        )
        if latest is None:
            raise ValueError("缺少最新 PIT 股票池快照")
        eligible = set(universe_membership.eligible_codes(latest))
        if not set(codes) <= eligible:
            raise ValueError("部分 Challenger 标的不在最新 PIT 股票池")
        program = EvolutionProgram(
            id=str(uuid4()),
            model_run_id=model_run_id,
            model_artifact_sha256=model.artifact_sha256,
            model_data_sha256=model.data_sha256,
            attestation_key_id=settings.evolution_attestation_key_id,
            created_by_user_id=created_by_user_id,
            created_by_user_id_snapshot=created_by_user_id,
            stage="simulation",
            codes_json=dump_envelope(sorted(codes)),
            started_on=latest,
            stage_started_on=latest,
            simulation_sessions=0,
            shadow_sessions=0,
            initial_equity=INITIAL_EQUITY,
            cash=INITIAL_EQUITY,
            equity=INITIAL_EQUITY,
            peak_equity=INITIAL_EQUITY,
            holdings_json=dump_envelope({}),
            champion_cash=INITIAL_EQUITY,
            champion_equity=INITIAL_EQUITY,
            champion_holdings_json=dump_envelope({}),
            metrics_json=dump_envelope({}),
        )
        session.add(program)
        session.flush()
        _transition(
            session,
            program,
            to_stage="simulation",
            reason="oos_validated_enrollment",
            metrics={},
            as_of=latest,
        )
        return _summary(program)


def _summary(program: EvolutionProgram) -> dict[str, Any]:
    return {
        "id": program.id,
        "modelRunId": program.model_run_id,
        "modelArtifactSha256": program.model_artifact_sha256,
        "modelDataSha256": program.model_data_sha256,
        "attestationKeyId": program.attestation_key_id,
        "stage": program.stage,
        "codes": load_envelope(program.codes_json, expect="list"),
        "startedOn": program.started_on.isoformat(),
        "simulationSessions": program.simulation_sessions,
        "shadowSessions": program.shadow_sessions,
        "equity": program.equity,
        "cash": program.cash,
        "peakEquity": program.peak_equity,
        "holdings": load_envelope(
            program.holdings_json, expect="dict"
        ),
        "championCash": program.champion_cash,
        "championEquity": program.champion_equity,
        "championHoldings": load_envelope(
            program.champion_holdings_json, expect="dict"
        ),
        "metrics": load_envelope(program.metrics_json, expect="dict"),
        "failureReason": program.failure_reason,
        "executionEnabled": False,
    }


def _claim(program_id: str) -> tuple[str, dict[str, Any]]:
    token = str(uuid4())
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        program = session.execute(
            select(EvolutionProgram)
            .where(EvolutionProgram.id == program_id)
            .with_for_update()
        ).scalar_one_or_none()
        if program is None:
            raise ValueError("Challenger 计划不存在")
        if program.stage not in {"simulation", "shadow"}:
            raise ValueError("Challenger 当前阶段不可评估")
        if (
            program.claim_token
            and program.claim_started_at
            and _aware(program.claim_started_at)
            > now - CLAIM_LEASE
        ):
            raise EvolutionConflictError("Challenger 日评估正在运行")
        program.claim_token = token
        program.claim_started_at = now
        return token, _summary(program)


def _exact_bars(code: str, signal_date: date, label_date: date):
    bars, quality = runner.load_bars_with_quality(
        code,
        "1d",
        signal_date.isoformat(),
        label_date.isoformat(),
    )
    by_date = {bar.date: bar for bar in bars}
    if (
        quality != "full"
        or signal_date not in by_date
        or label_date not in by_date
    ):
        raise ValueError(f"{code} 模拟日线或复权质量不完整")
    return by_date[signal_date], by_date[label_date]


def _forecast_rows(
    model_run_id: str,
    signal_date: date,
    codes: list[str],
) -> list[dict[str, Any]]:
    features = prediction_training.build_inference_features_from_database(
        signal_date=signal_date, codes=codes
    )
    feature_by_code = {value.code: value for value in features}
    if set(feature_by_code) != set(codes):
        raise ValueError("部分 Challenger 标的缺少完整预测特征")
    with SessionLocal() as session:
        rows = session.execute(
            select(PredictionForecast).where(
                PredictionForecast.model_run_id == model_run_id,
                PredictionForecast.signal_date == signal_date,
                PredictionForecast.code.in_(codes),
            )
        ).scalars().all()
    existing_codes = {row.code for row in rows}
    missing_features = [
        feature_by_code[code]
        for code in codes
        if code not in existing_codes
    ]
    if missing_features:
        prediction_registry.infer_model_and_store(
            model_run_id, missing_features
        )
        with SessionLocal() as session:
            rows = session.execute(
                select(PredictionForecast).where(
                    PredictionForecast.model_run_id == model_run_id,
                    PredictionForecast.signal_date == signal_date,
                    PredictionForecast.code.in_(codes),
                )
            ).scalars().all()
    if len(rows) != len(codes):
        raise ValueError("Challenger 预测未完整落库")
    output = []
    for row in sorted(rows, key=lambda value: value.code):
        feature = feature_by_code[row.code]
        expected_feature_sha256 = hashlib.sha256(
            json.dumps(
                feature.features,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if row.feature_sha256 != expected_feature_sha256:
            raise ValueError("既有预测的特征 Hash 与当前 PIT 输入不一致")
        output.append(
            {
            "code": row.code,
            "probabilityUp": row.probability_up,
            "returnP10": row.return_p10,
            "returnP50": row.return_p50,
            "returnP90": row.return_p90,
            "featureSha256": row.feature_sha256,
            "features": feature.features,
        }
        )
    return output


def _targets(
    predictions: list[dict[str, Any]],
    *,
    regime: str,
    industries: dict[str, str],
    equity: float,
    drawdown: float,
) -> dict[str, float]:
    raw = {
        prediction["code"]: (
            max(0.0, (prediction["probabilityUp"] - 0.5) * 2)
            if prediction["returnP50"] > 0
            else 0.0
        )
        for prediction in predictions
    }
    losses = {
        prediction["code"]: max(0.0, -prediction["returnP10"])
        for prediction in predictions
    }
    allocation = allocate_portfolio(
        proposals=[
            StrategyProposal(
                strategy_id="challenger-paper",
                category="multi_factor",
                confidence=1.0,
                target_weights=raw,
            )
        ],
        regime=regime,
        equity=min(equity, INITIAL_EQUITY),
        industries=industries,
        predicted_loss_rates=losses,
        drawdown=drawdown,
    )
    return allocation["weights"]


def _rebalance(
    *,
    cash: float,
    holdings: dict[str, int],
    targets: dict[str, float],
    signal_bars: dict[str, Any],
    label_bars: dict[str, Any],
) -> tuple[float, dict[str, int], float, list[dict[str, Any]]]:
    pre_open_equity = cash + sum(
        qty * label_bars[code].open for code, qty in holdings.items()
    )
    desired = {}
    for code, weight in targets.items():
        price = label_bars[code].open * 1.001
        desired[code] = max(
            0, int((pre_open_equity * weight) // (price * 100)) * 100
        )
    fills = []
    new_holdings = dict(holdings)
    for code in sorted(set(holdings) | set(desired)):
        current = new_holdings.get(code, 0)
        target = desired.get(code, 0)
        if current <= target:
            continue
        bar = label_bars[code]
        signal = signal_bars[code]
        capacity = int((signal.volume * 0.01) // 100) * 100
        qty = min(current - target, capacity)
        if qty <= 0:
            continue
        if (
            bar.limit_ratio
            and bar.previous_close
            and bar.open
            <= round(bar.previous_close * (1 - bar.limit_ratio), 2)
        ):
            continue
        lower_limit = (
            round(bar.previous_close * (1 - bar.limit_ratio), 2)
            if bar.limit_ratio and bar.previous_close
            else 0.01
        )
        price = max(lower_limit, bar.open * 0.999)
        value = price * qty
        fee = commission(value)
        tax = stamp_tax(value, "sell", label_bars[code].date)
        cash += value - fee - tax
        new_holdings[code] = current - qty
        fills.append(
            {
                "code": code,
                "side": "sell",
                "qty": qty,
                "price": price,
                "fee": fee,
                "tax": tax,
            }
        )
    for code in sorted(desired):
        current = new_holdings.get(code, 0)
        target = desired[code]
        if current >= target:
            continue
        bar = label_bars[code]
        signal = signal_bars[code]
        capacity = int((signal.volume * 0.01) // 100) * 100
        qty = min(target - current, capacity)
        if (
            qty <= 0
            or (
                bar.limit_ratio
                and bar.previous_close
                and bar.open
                >= round(bar.previous_close * (1 + bar.limit_ratio), 2)
            )
        ):
            continue
        upper_limit = (
            round(bar.previous_close * (1 + bar.limit_ratio), 2)
            if bar.limit_ratio and bar.previous_close
            else bar.open * 1.001
        )
        price = min(upper_limit, bar.open * 1.001)
        while qty > 0:
            value = price * qty
            fee = commission(value)
            if value + fee <= cash:
                break
            qty -= 100
        if qty <= 0:
            continue
        cash -= price * qty + commission(price * qty)
        new_holdings[code] = current + qty
        fills.append(
            {
                "code": code,
                "side": "buy",
                "qty": qty,
                "price": price,
                "fee": commission(price * qty),
                "tax": 0.0,
            }
        )
    new_holdings = {
        code: qty for code, qty in new_holdings.items() if qty > 0
    }
    equity = cash + sum(
        qty * label_bars[code].close
        for code, qty in new_holdings.items()
    )
    return cash, new_holdings, equity, fills


def _metrics(observations: list[EvolutionObservation]) -> dict[str, Any]:
    if not observations:
        return {}
    payloads = [
        load_envelope(row.payload_json, expect="dict")
        for row in observations
    ]
    returns = [row.daily_return for row in observations]
    benchmark_returns = [row.benchmark_return for row in observations]
    compounded = math.prod(1 + value for value in returns) - 1
    benchmark = math.prod(1 + value for value in benchmark_returns) - 1
    annual = (
        (1 + compounded) ** (252 / len(returns)) - 1
        if compounded > -1
        else -1.0
    )
    sharpe = (
        mean(returns) / stdev(returns) * math.sqrt(252)
        if len(returns) > 1 and stdev(returns) > 0
        else 0.0
    )
    equities = [observations[0].equity / (1 + returns[0])] + [
        row.equity for row in observations
    ]
    peak = equities[0]
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        max_drawdown = max(
            max_drawdown, (peak - equity) / peak if peak else 0.0
        )
    outcomes = [
        payload["portfolioOutcome"]
        for payload in payloads
        if payload.get("portfolioOutcome") is not None
    ]
    positives = [item for item in outcomes if item["actualUp"]]
    negatives = [item for item in outcomes if not item["actualUp"]]
    tpr = (
        sum(item["predictedUp"] for item in positives) / len(positives)
        if positives
        else 0.0
    )
    tnr = (
        sum(not item["predictedUp"] for item in negatives) / len(negatives)
        if negatives
        else 0.0
    )
    balanced_accuracy = (tpr + tnr) / 2 if positives and negatives else 0.0
    return {
        "sessions": len(observations),
        "predictionSessions": len(outcomes),
        "totalReturn": compounded,
        "annualizedReturn": annual,
        "benchmarkReturn": benchmark,
        "excessReturn": compounded - benchmark,
        "sharpe": sharpe,
        "maxDrawdown": max_drawdown,
        "balancedAccuracy": balanced_accuracy,
        "directionClassCount": len(
            {item["actualUp"] for item in outcomes}
        ),
    }


def _passes(metrics: dict[str, Any]) -> bool:
    return (
        metrics.get("annualizedReturn", -1) > 0
        and metrics.get("predictionSessions", 0)
        >= math.ceil(metrics.get("sessions", 0) * 0.8)
        and metrics.get("sharpe", 0) >= 1
        and metrics.get("maxDrawdown", 1) <= 0.20
        and metrics.get("excessReturn", -1) > 0
        and metrics.get("balancedAccuracy", 0) >= 0.53
    )


def _single_bar(code: str, day: date):
    bars, quality = runner.load_bars_with_quality(
        code, "1d", day.isoformat(), day.isoformat()
    )
    if quality != "full" or len(bars) != 1 or bars[0].date != day:
        raise ValueError(f"{code} 承诺日线或复权质量不完整")
    return bars[0]


def _bar_payload(bar) -> dict[str, Any]:
    return {
        "code": bar.code,
        "date": bar.date.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
        "previousClose": bar.previous_close,
        "limitRatio": bar.limit_ratio,
        "statusType": bar.status_type,
    }


def commit_signal(
    program_id: str,
    *,
    signal_date: date,
) -> dict[str, Any]:
    with SessionLocal() as session:
        existing = session.execute(
            select(EvolutionSignalCommitment).where(
                EvolutionSignalCommitment.program_id == program_id,
                EvolutionSignalCommitment.signal_date == signal_date,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {
                "id": existing.id,
                "programId": program_id,
                "signalDate": signal_date.isoformat(),
                "labelDate": existing.label_date.isoformat(),
                "committed": True,
                "executionEnabled": False,
            }
    token, claimed = _claim(program_id)
    try:
        started = date.fromisoformat(claimed["startedOn"])
        with SessionLocal() as session:
            program = session.get(EvolutionProgram, program_id)
            expected_signal = (
                started
                if program.last_signal_date is None
                else _next_session(program.last_signal_date)
            )
            latest_snapshot = session.get(
                UniverseSnapshotDaily,
                {
                    "trade_date": signal_date,
                    "rules_version": universe_membership.RULES_VERSION,
                },
            )
            latest_date = session.scalar(
                select(func.max(UniverseSnapshotDaily.trade_date)).where(
                    UniverseSnapshotDaily.rules_version
                    == universe_membership.RULES_VERSION
                )
            )
            model = session.get(
                PredictionModelRun, program.model_run_id
            )
            unsettled = session.scalar(
                select(func.count(EvolutionSignalCommitment.id)).where(
                    EvolutionSignalCommitment.program_id == program_id,
                    ~EvolutionSignalCommitment.id.in_(
                        select(EvolutionObservation.commitment_id)
                    ),
                )
            )
        if signal_date != expected_signal or signal_date != latest_date:
            raise ValueError(
                "Signal Commitment 必须在最新连续交易日生成，禁止补录"
            )
        if unsettled:
            raise ValueError("上一 Signal Commitment 尚未结算")
        if (
            latest_snapshot is None
            or model is None
            or model.artifact_sha256
            != claimed.get("modelArtifactSha256")
        ):
            raise ValueError("Challenger 模型或股票池证据已变化")
        codes = claimed["codes"]
        predictions = _forecast_rows(
            claimed["modelRunId"], signal_date, codes
        )
        signal_bars = {
            code: _single_bar(code, signal_date) for code in codes
        }
        with SessionLocal() as session:
            industry_evidence = (
                industry_history.industry_evidence_asof_in_session(
                    session, codes, signal_date
                )
            )
            regime = authoritative_allocation._authoritative_regime(
                session, signal_date
            )
        industries = {
            code: value["industry"]
            for code, value in industry_evidence.items()
        }
        drawdown = (
            max(
                0.0,
                (claimed["peakEquity"] - claimed["equity"])
                / claimed["peakEquity"],
            )
            if claimed["peakEquity"]
            else 0.0
        )
        targets = _targets(
            predictions,
            regime=regime["regime"],
            industries=industries,
            equity=claimed["equity"],
            drawdown=drawdown,
        )
        comparator: dict[str, Any]
        if claimed["stage"] == "shadow":
            try:
                with SessionLocal() as session:
                    champion = prediction_registry._champion(session)
                if champion.id == claimed["modelRunId"]:
                    raise ValueError(
                        "Challenger 不得与自身 Champion 比较"
                    )
                comparator_predictions = _forecast_rows(
                    champion.id, signal_date, codes
                )
                comparator = {
                    "type": "champion",
                    "modelRunId": champion.id,
                    "artifactSha256": champion.artifact_sha256,
                    "predictions": comparator_predictions,
                    "targets": _targets(
                        comparator_predictions,
                        regime=regime["regime"],
                        industries=industries,
                        equity=claimed["equity"],
                        drawdown=0.0,
                    ),
                }
            except ValueError as exc:
                if "当前没有可信 Champion" not in str(exc):
                    raise
                comparator = {
                    "type": "bootstrap_cash",
                    "modelRunId": None,
                    "predictions": [],
                    "targets": {},
                }
        else:
            comparator = {"type": "none"}
        label_date = _next_session(signal_date)
        committed_at = datetime.now(UTC)
        evidence = {
            "programId": program_id,
            "stage": claimed["stage"],
            "signalDate": signal_date.isoformat(),
            "labelDate": label_date.isoformat(),
            "committedAt": committed_at.isoformat(),
            "modelRunId": claimed["modelRunId"],
            "modelArtifactSha256": model.artifact_sha256,
            "modelDataSha256": model.data_sha256,
            "universeMembershipSha256": (
                latest_snapshot.membership_sha256
            ),
            "industryEvidence": industry_evidence,
            "regime": regime,
            "signalBars": {
                code: _bar_payload(bar)
                for code, bar in signal_bars.items()
            },
            "predictions": predictions,
            "targets": targets,
            "comparator": comparator,
            "preState": {
                "cash": claimed["cash"],
                "equity": claimed["equity"],
                "holdings": claimed["holdings"],
                "championCash": claimed["championCash"],
                "championEquity": claimed["championEquity"],
                "championHoldings": claimed["championHoldings"],
            },
            "executionEnabled": False,
        }
        evidence_sha256 = _hash(evidence)
        commitment_id = str(uuid4())
        with SessionLocal.begin() as session:
            program = session.execute(
                select(EvolutionProgram)
                .where(
                    EvolutionProgram.id == program_id,
                    EvolutionProgram.claim_token == token,
                )
                .with_for_update()
            ).scalar_one()
            if (
                program.last_signal_date is not None
                and signal_date <= program.last_signal_date
            ):
                raise ValueError("Signal Commitment 日期未前进")
            session.add(
                EvolutionSignalCommitment(
                    id=commitment_id,
                    program_id=program_id,
                    stage=program.stage,
                    signal_date=signal_date,
                    label_date=label_date,
                    model_artifact_sha256=program.model_artifact_sha256,
                    universe_membership_sha256=(
                        latest_snapshot.membership_sha256
                    ),
                    evidence_sha256=evidence_sha256,
                    attestation_sha256=_attest(
                        "commitment",
                        evidence_sha256,
                        {
                            "programId": program_id,
                            "signalDate": signal_date.isoformat(),
                            "stage": program.stage,
                        },
                        key_id=program.attestation_key_id,
                    ),
                    payload_json=dump_envelope(evidence),
                    committed_at=committed_at,
                )
            )
            program.last_signal_date = signal_date
            program.claim_token = None
            program.claim_started_at = None
        return {
            "id": commitment_id,
            "programId": program_id,
            "signalDate": signal_date.isoformat(),
            "labelDate": label_date.isoformat(),
            "committed": True,
            "executionEnabled": False,
        }
    except Exception:
        with SessionLocal.begin() as session:
            program = session.execute(
                select(EvolutionProgram)
                .where(
                    EvolutionProgram.id == program_id,
                    EvolutionProgram.claim_token == token,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if program is not None:
                program.claim_token = None
                program.claim_started_at = None
        raise


def evaluate_day(program_id: str, *, signal_date: date) -> dict[str, Any]:
    with SessionLocal() as session:
        existing = session.execute(
            select(EvolutionObservation.id)
            .join(
                EvolutionSignalCommitment,
                EvolutionSignalCommitment.id
                == EvolutionObservation.commitment_id,
            )
            .where(
                EvolutionSignalCommitment.program_id == program_id,
                EvolutionSignalCommitment.signal_date == signal_date,
            )
        ).scalar_one_or_none()
    if existing is not None:
        return get(program_id)
    token, claimed = _claim(program_id)
    try:
        stage = claimed["stage"]
        codes = claimed["codes"]
        with SessionLocal() as session:
            program = session.get(EvolutionProgram, program_id)
            commitment = session.execute(
                select(EvolutionSignalCommitment).where(
                    EvolutionSignalCommitment.program_id == program_id,
                    EvolutionSignalCommitment.signal_date == signal_date,
                )
            ).scalar_one_or_none()
            settled = (
                session.execute(
                    select(EvolutionObservation.id).where(
                        EvolutionObservation.commitment_id
                        == commitment.id
                    )
                ).scalar_one_or_none()
                if commitment is not None
                else None
            )
        if commitment is None:
            raise ValueError("缺少开盘前不可变 Signal Commitment")
        if settled is not None:
            with SessionLocal.begin() as session:
                program = session.execute(
                    select(EvolutionProgram)
                    .where(
                        EvolutionProgram.id == program_id,
                        EvolutionProgram.claim_token == token,
                    )
                    .with_for_update()
                ).scalar_one()
                program.claim_token = None
                program.claim_started_at = None
            return get(program_id)
        commitment_payload = load_envelope(
            commitment.payload_json, expect="dict"
        )
        if (
            _hash(commitment_payload) != commitment.evidence_sha256
            or commitment.model_artifact_sha256
            != claimed["modelArtifactSha256"]
            or commitment.stage != stage
        ):
            raise ValueError("Signal Commitment 证据校验失败")
        label_date = commitment.label_date
        with SessionLocal() as session:
            signal_snapshot = session.get(
                UniverseSnapshotDaily,
                {
                    "trade_date": signal_date,
                    "rules_version": universe_membership.RULES_VERSION,
                },
            )
            label_snapshot = session.get(
                UniverseSnapshotDaily,
                {
                    "trade_date": label_date,
                    "rules_version": universe_membership.RULES_VERSION,
                },
            )
            latest = session.scalar(
                select(func.max(UniverseSnapshotDaily.trade_date)).where(
                    UniverseSnapshotDaily.rules_version
                    == universe_membership.RULES_VERSION
                )
            )
        if latest is None or label_date != latest:
            raise ValueError("仅允许评估最新已物化交易日，禁止事后回填")
        if (
            signal_snapshot is None
            or label_snapshot is None
            or signal_snapshot.membership_sha256
            != commitment.universe_membership_sha256
            or _aware(label_snapshot.computed_at)
            <= _aware(commitment.committed_at)
        ):
            raise ValueError("Commitment 不是在次日物化前生成")
        recomputed_features = {
            value.code: value.features
            for value in (
                prediction_training.build_inference_features_from_database(
                    signal_date=signal_date, codes=codes
                )
            )
        }
        if any(
            prediction.get("features")
            != recomputed_features.get(prediction["code"])
            for prediction in commitment_payload["predictions"]
        ):
            raise ValueError("承诺后的 PIT 特征输入发生变化")
        with SessionLocal() as session:
            industry_evidence = (
                industry_history.industry_evidence_asof_in_session(
                    session, codes, signal_date
                )
            )
            regime_evidence = (
                authoritative_allocation._authoritative_regime(
                    session, signal_date
                )
            )
        if (
            industry_evidence
            != commitment_payload["industryEvidence"]
            or regime_evidence != commitment_payload["regime"]
        ):
            raise ValueError("承诺后的行业或市场状态证据发生变化")
        candidate_predictions = commitment_payload["predictions"]
        candidate_targets = commitment_payload["targets"]
        signal_bars = {}
        label_bars = {}
        for code in codes:
            signal_bars[code], label_bars[code] = _exact_bars(
                code, signal_date, label_date
            )
            if (
                _bar_payload(signal_bars[code])
                != commitment_payload["signalBars"][code]
            ):
                raise ValueError("承诺后的信号日行情发生变化")
        benchmark_signal, benchmark_label = _exact_bars(
            "000300.SH", signal_date, label_date
        )
        with SessionLocal.begin() as session:
            program = session.execute(
                select(EvolutionProgram)
                .where(
                    EvolutionProgram.id == program_id,
                    EvolutionProgram.claim_token == token,
                )
                .with_for_update()
            ).scalar_one()
            holdings = load_envelope(
                program.holdings_json, expect="dict"
            )
            pre_state = commitment_payload["preState"]
            if (
                abs(float(pre_state["cash"]) - program.cash) > 1e-6
                or abs(float(pre_state["equity"]) - program.equity)
                > 1e-6
                or pre_state["holdings"] != holdings
                or abs(
                    float(pre_state["championCash"])
                    - program.champion_cash
                )
                > 1e-6
                or abs(
                    float(pre_state["championEquity"])
                    - program.champion_equity
                )
                > 1e-6
                or pre_state["championHoldings"]
                != load_envelope(
                    program.champion_holdings_json, expect="dict"
                )
            ):
                raise ValueError(
                    "结算前组合状态与 Signal Commitment 不一致"
                )
            prior_equity = program.equity
            cash, holdings, equity, fills = _rebalance(
                cash=program.cash,
                holdings={k: int(v) for k, v in holdings.items()},
                targets=candidate_targets,
                signal_bars=signal_bars,
                label_bars=label_bars,
            )
            champion_return = None
            champion_payload = None
            benchmark_return = (
                benchmark_label.close / benchmark_signal.close - 1
            )
            if stage == "shadow":
                comparator = commitment_payload["comparator"]
                previous_champion_equity = program.champion_equity
                if comparator["type"] == "champion":
                    champion_holdings = load_envelope(
                        program.champion_holdings_json, expect="dict"
                    )
                    (
                        program.champion_cash,
                        champion_holdings,
                        champion_equity,
                        champion_fills,
                    ) = _rebalance(
                        cash=program.champion_cash,
                        holdings={
                            k: int(v)
                            for k, v in champion_holdings.items()
                        },
                        targets=comparator["targets"],
                        signal_bars=signal_bars,
                        label_bars=label_bars,
                    )
                    program.champion_holdings_json = dump_envelope(
                        champion_holdings
                    )
                else:
                    champion_equity = previous_champion_equity
                    program.champion_cash = champion_equity
                    champion_fills = []
                champion_return = (
                    champion_equity / previous_champion_equity - 1
                    if previous_champion_equity
                    else 0.0
                )
                program.champion_equity = champion_equity
                champion_payload = {
                    **comparator,
                    "fills": champion_fills,
                    "dailyReturn": champion_return,
                    "equity": champion_equity,
                }
            daily_return = (
                equity / prior_equity - 1 if prior_equity else 0.0
            )
            prediction_by_code = {
                value["code"]: value for value in candidate_predictions
            }
            outcomes = []
            for code in codes:
                prediction = prediction_by_code[code]
                realized = (
                    label_bars[code].close / label_bars[code].open - 1
                )
                outcomes.append(
                    {
                        "code": code,
                        "probabilityUp": prediction["probabilityUp"],
                        "predictedUp": prediction["probabilityUp"] >= 0.5,
                        "actualUp": realized > 0,
                        "realizedOpenCloseReturn": realized,
                        "intervalCovered": (
                            prediction["returnP10"]
                            <= realized
                            <= prediction["returnP90"]
                        ),
                    }
                )
            end_exposures = {
                code: qty * label_bars[code].close / equity
                for code, qty in holdings.items()
                if equity > 0 and code in prediction_by_code
            }
            gross_exposure = sum(end_exposures.values())
            portfolio_outcome = None
            if gross_exposure > 0:
                normalized_exposure = {
                    code: weight / gross_exposure
                    for code, weight in end_exposures.items()
                }
                intraday_return = sum(
                    normalized_exposure[code]
                    * (
                        label_bars[code].close
                        / label_bars[code].open
                        - 1
                    )
                    for code in normalized_exposure
                )
                expected_median = sum(
                    normalized_exposure[code]
                    * prediction_by_code[code]["returnP50"]
                    for code in normalized_exposure
                )
                portfolio_outcome = {
                    "predictedUp": expected_median > 0,
                    "actualUp": intraday_return > 0,
                    "realizedOpenCloseReturn": intraday_return,
                    "expectedMedianReturn": expected_median,
                    "grossExposure": gross_exposure,
                }
            payload = {
                "programId": program.id,
                "commitmentId": commitment.id,
                "commitmentEvidenceSha256": commitment.evidence_sha256,
                "commitment": commitment_payload,
                "modelRunId": program.model_run_id,
                "stage": stage,
                "signalDate": signal_date.isoformat(),
                "labelDate": label_date.isoformat(),
                "predictions": candidate_predictions,
                "targets": candidate_targets,
                "fills": fills,
                "holdings": holdings,
                "cash": cash,
                "equity": equity,
                "dailyReturn": daily_return,
                "benchmarkReturn": benchmark_return,
                "outcomes": outcomes,
                "portfolioOutcome": portfolio_outcome,
                "champion": champion_payload,
                "executionEnabled": False,
            }
            observation_evidence_sha256 = _hash(payload)
            observation = EvolutionObservation(
                id=str(uuid4()),
                commitment_id=commitment.id,
                program_id=program.id,
                stage=stage,
                signal_date=signal_date,
                label_date=label_date,
                daily_return=daily_return,
                benchmark_return=benchmark_return,
                equity=equity,
                evidence_sha256=observation_evidence_sha256,
                attestation_sha256=_attest(
                    "observation",
                    observation_evidence_sha256,
                    {
                        "programId": program.id,
                        "commitmentId": commitment.id,
                        "signalDate": signal_date.isoformat(),
                    },
                    key_id=program.attestation_key_id,
                ),
                payload_json=dump_envelope(payload),
            )
            session.add(observation)
            program.cash = cash
            program.holdings_json = dump_envelope(holdings)
            program.equity = equity
            program.peak_equity = max(program.peak_equity, equity)
            program.last_signal_date = signal_date
            if stage == "simulation":
                program.simulation_sessions += 1
            else:
                program.shadow_sessions += 1
            session.flush()
            stage_observations = session.execute(
                select(EvolutionObservation)
                .where(
                    EvolutionObservation.program_id == program.id,
                    EvolutionObservation.stage == stage,
                )
                .order_by(EvolutionObservation.signal_date)
            ).scalars().all()
            metrics = _metrics(stage_observations)
            if stage == "shadow":
                champion_returns = [
                    load_envelope(row.payload_json, expect="dict")
                    .get("champion", {})
                    .get("dailyReturn", 0.0)
                    for row in stage_observations
                ]
                metrics["championReturn"] = (
                    math.prod(1 + value for value in champion_returns) - 1
                )
                metrics["challengerVsChampion"] = (
                    metrics["totalReturn"] - metrics["championReturn"]
                )
                paired = [
                    row.daily_return - champion_return
                    for row, champion_return in zip(
                        stage_observations,
                        champion_returns,
                        strict=True,
                    )
                ]
                metrics["pairedMeanDailyExcess"] = mean(paired)
                metrics["pairedLower95"] = (
                    mean(paired)
                    - 1.729 * stdev(paired) / math.sqrt(len(paired))
                    if len(paired) > 1
                    else -1.0
                )
            program.metrics_json = dump_envelope(metrics)
            minimum = (
                SIMULATION_SESSIONS
                if stage == "simulation"
                else SHADOW_SESSIONS
            )
            if len(stage_observations) >= 20 and (
                metrics["maxDrawdown"] > 0.20
                or math.prod(
                    1 + row.daily_return
                    for row in stage_observations[-20:]
                )
                - 1
                < -0.05
                or (
                    metrics["directionClassCount"] == 2
                    and metrics["balancedAccuracy"] < 0.45
                )
            ):
                program.failure_reason = "automatic_quality_downgrade"
                _transition(
                    session,
                    program,
                    to_stage="degraded",
                    reason=program.failure_reason,
                    metrics=metrics,
                    as_of=label_date,
                )
            elif len(stage_observations) == minimum:
                passes = _passes(metrics) and (
                    stage != "shadow"
                    or metrics["pairedLower95"] > 0
                )
                if passes and stage == "simulation":
                    _transition(
                        session,
                        program,
                        to_stage="shadow",
                        reason="simulation_60_session_gate_passed",
                        metrics=metrics,
                        as_of=label_date,
                    )
                    program.cash = program.equity
                    program.holdings_json = dump_envelope({})
                    program.peak_equity = program.equity
                    program.champion_cash = program.equity
                    program.champion_equity = program.equity
                    program.champion_holdings_json = dump_envelope({})
                elif passes:
                    _transition(
                        session,
                        program,
                        to_stage="eligible_for_small_capital",
                        reason="shadow_20_session_gate_passed",
                        metrics=metrics,
                        as_of=label_date,
                    )
                else:
                    program.failure_reason = f"{stage}_quality_gate_failed"
                    _transition(
                        session,
                        program,
                        to_stage="degraded",
                        reason=program.failure_reason,
                        metrics=metrics,
                        as_of=label_date,
                    )
            program.claim_token = None
            program.claim_started_at = None
        return get(program_id)
    except Exception:
        with SessionLocal.begin() as session:
            program = session.execute(
                select(EvolutionProgram)
                .where(
                    EvolutionProgram.id == program_id,
                    EvolutionProgram.claim_token == token,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if program is not None:
                program.claim_token = None
                program.claim_started_at = None
        raise


def get(program_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        program = session.get(EvolutionProgram, program_id)
        if program is None:
            raise ValueError("Challenger 计划不存在")
        observations = session.scalar(
            select(func.count(EvolutionObservation.id)).where(
                EvolutionObservation.program_id == program_id
            )
        )
        transitions = session.execute(
            select(EvolutionTransition)
            .where(EvolutionTransition.program_id == program_id)
            .order_by(EvolutionTransition.sequence)
        ).scalars().all()
        return {
            **_summary(program),
            "observationCount": observations,
            "transitions": [
                load_envelope(row.payload_json, expect="dict")
                for row in transitions
            ],
        }


def list_programs(*, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(EvolutionProgram)
            .order_by(EvolutionProgram.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_summary(row) for row in rows]


def verify_promotion_eligibility(
    session,
    model: PredictionModelRun,
) -> EvolutionProgram:
    program = session.execute(
        select(EvolutionProgram).where(
            EvolutionProgram.model_run_id == model.id
        )
    ).scalar_one_or_none()
    if (
        program is None
        or program.stage != "eligible_for_small_capital"
        or program.model_artifact_sha256 != model.artifact_sha256
        or program.model_data_sha256 != model.data_sha256
    ):
        raise ValueError("候选未绑定已完成的 M6 模拟计划")
    observations = session.execute(
        select(EvolutionObservation)
        .where(EvolutionObservation.program_id == program.id)
        .order_by(EvolutionObservation.signal_date)
    ).scalars().all()
    simulation = [row for row in observations if row.stage == "simulation"]
    shadow = [row for row in observations if row.stage == "shadow"]
    if (
        len(simulation) != SIMULATION_SESSIONS
        or len(shadow) != SHADOW_SESSIONS
        or program.simulation_sessions != SIMULATION_SESSIONS
        or program.shadow_sessions != SHADOW_SESSIONS
    ):
        raise ValueError("候选未满足 60 日模拟和 20 日影子样本")
    commitments = session.execute(
        select(EvolutionSignalCommitment)
        .where(EvolutionSignalCommitment.program_id == program.id)
        .order_by(EvolutionSignalCommitment.signal_date)
    ).scalars().all()
    if len(commitments) != SIMULATION_SESSIONS + SHADOW_SESSIONS:
        raise ValueError("M6 Signal Commitment 数量不完整")
    commitment_by_id = {row.id: row for row in commitments}
    expected_signal = program.started_on
    for index, commitment in enumerate(commitments):
        expected_stage = (
            "simulation" if index < SIMULATION_SESSIONS else "shadow"
        )
        commitment_payload = load_envelope(
            commitment.payload_json, expect="dict"
        )
        label_snapshot = session.get(
            UniverseSnapshotDaily,
            {
                "trade_date": commitment.label_date,
                "rules_version": universe_membership.RULES_VERSION,
            },
        )
        if (
            commitment.signal_date != expected_signal
            or commitment.label_date
            != _next_session(commitment.signal_date)
            or commitment.stage != expected_stage
            or _hash(commitment_payload)
            != commitment.evidence_sha256
            or not hmac.compare_digest(
                commitment.attestation_sha256,
                _attest(
                    "commitment",
                    commitment.evidence_sha256,
                    {
                        "programId": program.id,
                        "signalDate": (
                            commitment.signal_date.isoformat()
                        ),
                        "stage": commitment.stage,
                    },
                    key_id=program.attestation_key_id,
                ),
            )
            or label_snapshot is None
            or _aware(label_snapshot.computed_at)
            <= _aware(commitment.committed_at)
        ):
            raise ValueError("M6 Commitment 连续性、时序或签名无效")
        expected_signal = _next_session(commitment.signal_date)
    observation_by_commitment = {
        row.commitment_id: row for row in observations
    }
    for commitment in commitments:
        observation = observation_by_commitment.get(commitment.id)
        if observation is None:
            raise ValueError("M6 Commitment 缺少结算观察")
        commitment = commitment_by_id.get(observation.commitment_id)
        payload = load_envelope(
            observation.payload_json, expect="dict"
        )
        if (
            commitment is None
            or _hash(payload) != observation.evidence_sha256
            or not hmac.compare_digest(
                observation.attestation_sha256,
                _attest(
                    "observation",
                    observation.evidence_sha256,
                    {
                        "programId": program.id,
                        "commitmentId": observation.commitment_id,
                        "signalDate": (
                            observation.signal_date.isoformat()
                        ),
                    },
                    key_id=program.attestation_key_id,
                ),
            )
            or observation.signal_date != commitment.signal_date
            or observation.label_date != commitment.label_date
            or commitment.model_artifact_sha256
            != program.model_artifact_sha256
            or _hash(
                load_envelope(
                    commitment.payload_json, expect="dict"
                )
            )
            != commitment.evidence_sha256
        ):
            raise ValueError("M6 观察或承诺证据 Hash 校验失败")
    simulation_metrics = _metrics(simulation)
    shadow_metrics = _metrics(shadow)
    champion_returns = [
        load_envelope(row.payload_json, expect="dict")["champion"][
            "dailyReturn"
        ]
        for row in shadow
    ]
    paired = [
        row.daily_return - champion_return
        for row, champion_return in zip(
            shadow, champion_returns, strict=True
        )
    ]
    paired_lower = mean(paired) - 1.729 * stdev(paired) / math.sqrt(
        len(paired)
    )
    if (
        not _passes(simulation_metrics)
        or not _passes(shadow_metrics)
        or paired_lower <= 0
    ):
        raise ValueError("M6 独立重算的统计门禁未通过")
    transitions = session.execute(
        select(EvolutionTransition)
        .where(EvolutionTransition.program_id == program.id)
        .order_by(EvolutionTransition.sequence)
    ).scalars().all()
    previous_transition_sha256 = None
    for sequence, transition in enumerate(transitions, start=1):
        transition_payload = load_envelope(
            transition.payload_json, expect="dict"
        )
        if (
            transition.sequence != sequence
            or transition.previous_transition_sha256
            != previous_transition_sha256
            or transition_payload.get("previousTransitionSha256")
            != previous_transition_sha256
            or transition.metrics_sha256
            != _hash(transition_payload.get("metrics"))
            or _hash(transition_payload) != transition.evidence_sha256
            or not hmac.compare_digest(
                transition.attestation_sha256,
                _attest(
                    "transition",
                    transition.evidence_sha256,
                    {
                        "programId": program.id,
                        "sequence": sequence,
                    },
                    key_id=program.attestation_key_id,
                ),
            )
        ):
            raise ValueError("M6 阶段转换链或签名无效")
        previous_transition_sha256 = transition.evidence_sha256
    final_transition = transitions[-1] if transitions else None
    transition_path = [
        (row.from_stage, row.to_stage) for row in transitions
    ]
    if transition_path != [
        ("simulation", "simulation"),
        ("simulation", "shadow"),
        ("shadow", "eligible_for_small_capital"),
    ]:
        raise ValueError("M6 阶段转换路径无效")
    if (
        final_transition is None
        or final_transition.to_stage != "eligible_for_small_capital"
        or _hash(
            load_envelope(
                final_transition.payload_json, expect="dict"
            )
        )
        != final_transition.evidence_sha256
    ):
        raise ValueError("M6 最终晋级审计证据无效")
    return program


def _attribute_override_batch(
    *,
    limit: int = 100,
    target_override_id: str | None = None,
) -> int:
    with SessionLocal() as session:
        statement = (
            select(DecisionOverride)
            .outerjoin(
                BehaviorAttribution,
                BehaviorAttribution.override_id == DecisionOverride.id,
            )
            .where(BehaviorAttribution.id.is_(None))
            .order_by(DecisionOverride.created_at)
            .limit(limit)
        )
        if target_override_id is not None:
            statement = statement.where(
                DecisionOverride.id == target_override_id
            )
        overrides = session.execute(statement).scalars().all()
    created = 0
    for override in overrides:
        with SessionLocal() as session:
            run = session.get(DecisionRun, override.run_id)
            allocation = (
                session.get(
                    PortfolioAllocationDecision,
                    run.allocation_decision_id,
                )
                if run is not None
                else None
            )
        if run is None or allocation is None:
            continue
        label_date = _next_session(run.as_of)
        with SessionLocal() as session:
            latest = session.scalar(
                select(func.max(UniverseSnapshotDaily.trade_date)).where(
                    UniverseSnapshotDaily.rules_version
                    == universe_membership.RULES_VERSION
                )
            )
        if latest is None or label_date > latest:
            continue
        allocation_payload = load_envelope(
            allocation.payload_json, expect="dict"
        )
        if (
            _hash(allocation_payload.get("input"))
            != allocation.input_sha256
            or _hash(allocation_payload.get("output"))
            != allocation.output_sha256
        ):
            raise ValueError("行为归因的 M3 权威证据 Hash 无效")
        strategy_weights = allocation_payload["output"]["weights"]
        override_weights = load_envelope(
            override.weights_json, expect="dict"
        )
        if override.action == "accept":
            human_weights = strategy_weights
        elif override.action == "reject":
            human_weights = {}
        else:
            human_weights = override_weights
        inputs = allocation_payload["input"]
        positions = inputs["positions"]
        codes = sorted(
            set(strategy_weights)
            | set(human_weights)
            | {position["code"] for position in positions}
        )
        signal_bars = {}
        label_bars = {}
        bar_evidence = {}
        for code in codes:
            signal_bar, label_bar = _exact_bars(
                code, run.as_of, label_date
            )
            signal_bars[code] = signal_bar
            label_bars[code] = label_bar
            bar_evidence[code] = {
                "signal": _bar_payload(signal_bar),
                "label": _bar_payload(label_bar),
            }
        starting_holdings = {
            position["code"]: int(position["qty"])
            for position in positions
        }
        available_cash = float(inputs["account"]["cash"])
        frozen_cash = float(inputs["account"]["frozenCash"])
        starting_equity = float(inputs["account"]["totalAssets"])
        (
            strategy_cash,
            strategy_holdings,
            strategy_equity,
            strategy_fills,
        ) = _rebalance(
            cash=available_cash,
            holdings=starting_holdings,
            targets=strategy_weights,
            signal_bars=signal_bars,
            label_bars=label_bars,
        )
        (
            human_cash,
            human_holdings,
            human_equity,
            human_fills,
        ) = _rebalance(
            cash=available_cash,
            holdings=starting_holdings,
            targets=human_weights,
            signal_bars=signal_bars,
            label_bars=label_bars,
        )
        strategy_equity += frozen_cash
        human_equity += frozen_cash
        strategy_return = strategy_equity / starting_equity - 1
        human_return = human_equity / starting_equity - 1
        strategy_gross = sum(
            float(value) for value in strategy_weights.values()
        )
        human_gross = sum(
            float(value) for value in human_weights.values()
        )
        flags = []
        if override.action == "reject":
            flags.append("rejected_strategy")
        if human_gross > strategy_gross + 1e-9:
            flags.append("increased_exposure")
        elif human_gross < strategy_gross - 1e-9:
            flags.append("reduced_exposure")
        if human_weights != strategy_weights:
            flags.append("deviated_from_strategy")
        evidence = {
            "overrideId": override.id,
            "overrideEvidenceSha256": override.evidence_sha256,
            "allocationInputSha256": allocation.input_sha256,
            "allocationOutputSha256": allocation.output_sha256,
            "strategyWeights": strategy_weights,
            "humanWeights": human_weights,
            "bars": bar_evidence,
            "flags": flags,
            "startingState": {
                "cash": available_cash,
                "frozenCash": frozen_cash,
                "equity": starting_equity,
                "holdings": starting_holdings,
            },
            "strategyResult": {
                "cash": strategy_cash,
                "holdings": strategy_holdings,
                "equity": strategy_equity,
                "fills": strategy_fills,
                "return": strategy_return,
            },
            "humanResult": {
                "cash": human_cash,
                "holdings": human_holdings,
                "equity": human_equity,
                "fills": human_fills,
                "return": human_return,
            },
        }
        try:
            with SessionLocal.begin() as session:
                session.add(
                    BehaviorAttribution(
                        id=str(uuid4()),
                        override_id=override.id,
                        user_id=override.user_id,
                        user_id_snapshot=override.user_id_snapshot,
                        signal_date=run.as_of,
                        label_date=label_date,
                        strategy_return=strategy_return,
                        human_return=human_return,
                        return_delta=human_return - strategy_return,
                        behavior_json=dump_envelope(
                            evidence
                        ),
                        evidence_sha256=_hash(evidence),
                    )
                )
            created += 1
        except IntegrityError:
            continue
    return created


def attribute_due_overrides(*, limit: int = 100) -> int:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        candidates = session.execute(
            select(DecisionOverride.id)
            .outerjoin(
                BehaviorAttribution,
                BehaviorAttribution.override_id == DecisionOverride.id,
            )
            .outerjoin(
                BehaviorAttributionAttempt,
                BehaviorAttributionAttempt.override_id
                == DecisionOverride.id,
            )
            .where(
                BehaviorAttribution.id.is_(None),
                (
                    BehaviorAttributionAttempt.override_id.is_(None)
                    | (
                        (
                            BehaviorAttributionAttempt.status
                            == "retry"
                        )
                        & (
                            BehaviorAttributionAttempt.next_attempt_at
                            <= now
                        )
                    )
                ),
            )
            .order_by(DecisionOverride.created_at)
            .limit(limit)
        ).scalars().all()
    created = 0
    for override_id in candidates:
        try:
            result = _attribute_override_batch(
                limit=1, target_override_id=override_id
            )
            if result:
                created += result
                with SessionLocal.begin() as session:
                    attempt = session.get(
                        BehaviorAttributionAttempt, override_id
                    )
                    if attempt is not None:
                        attempt.status = "completed"
                        attempt.last_error_code = None
            continue
        except Exception as exc:  # noqa: BLE001
            try:
                with SessionLocal.begin() as session:
                    attempt = session.execute(
                        select(BehaviorAttributionAttempt)
                        .where(
                            BehaviorAttributionAttempt.override_id
                            == override_id
                        )
                        .with_for_update()
                    ).scalar_one_or_none()
                    if attempt is None:
                        attempt = BehaviorAttributionAttempt(
                            override_id=override_id,
                            status="retry",
                            attempts=0,
                            next_attempt_at=now,
                        )
                        session.add(attempt)
                    attempt.attempts += 1
                    attempt.last_error_code = type(exc).__name__[:64]
                    if attempt.attempts >= 6:
                        attempt.status = "failed"
                    else:
                        attempt.status = "retry"
                        attempt.next_attempt_at = now + timedelta(
                            seconds=min(
                                3600,
                                60 * (2 ** (attempt.attempts - 1)),
                            )
                        )
            except Exception:  # noqa: BLE001
                pass
    return created


def process_due_programs(*, limit: int = 20) -> int:
    with SessionLocal() as session:
        latest = session.scalar(
            select(func.max(UniverseSnapshotDaily.trade_date)).where(
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION
            )
        )
        programs = session.execute(
            select(EvolutionProgram)
            .where(EvolutionProgram.stage.in_(["simulation", "shadow"]))
            .order_by(EvolutionProgram.updated_at)
            .limit(limit)
        ).scalars().all()
    processed = 0
    for listed_program in programs:
        if latest is None:
            continue
        try:
            with SessionLocal() as session:
                unsettled = session.execute(
                    select(EvolutionSignalCommitment).where(
                        EvolutionSignalCommitment.program_id
                        == listed_program.id,
                        EvolutionSignalCommitment.label_date == latest,
                        ~EvolutionSignalCommitment.id.in_(
                            select(
                                EvolutionObservation.commitment_id
                            )
                        ),
                    )
                ).scalar_one_or_none()
            if unsettled is not None:
                evaluate_day(
                    listed_program.id,
                    signal_date=unsettled.signal_date,
                )
                processed += 1
            with SessionLocal() as session:
                current = session.get(
                    EvolutionProgram, listed_program.id
                )
                if current.stage not in {"simulation", "shadow"}:
                    continue
                expected_signal = (
                    current.started_on
                    if current.last_signal_date is None
                    else _next_session(current.last_signal_date)
                )
            if expected_signal < latest:
                with SessionLocal.begin() as session:
                    current = session.execute(
                        select(EvolutionProgram)
                        .where(
                            EvolutionProgram.id == listed_program.id
                        )
                        .with_for_update()
                    ).scalar_one()
                    current.failure_reason = "missed_signal_commitment"
                    _transition(
                        session,
                        current,
                        to_stage="degraded",
                        reason="missed_signal_commitment",
                        metrics=load_envelope(
                            current.metrics_json, expect="dict"
                        ),
                        as_of=latest,
                    )
            elif expected_signal == latest:
                commit_signal(
                    listed_program.id, signal_date=latest
                )
        except EvolutionConflictError:
            continue
        except ValueError as exc:
            with SessionLocal.begin() as session:
                current = session.execute(
                    select(EvolutionProgram)
                    .where(EvolutionProgram.id == listed_program.id)
                    .with_for_update()
                ).scalar_one_or_none()
                if current is not None and current.stage in {
                    "simulation",
                    "shadow",
                }:
                    current.failure_reason = (
                        f"daily_evaluation_blocked:{type(exc).__name__}"
                    )
                    _transition(
                        session,
                        current,
                        to_stage="paused",
                        reason=current.failure_reason,
                        metrics=load_envelope(
                            current.metrics_json, expect="dict"
                        ),
                        as_of=latest,
                    )
            continue
    return processed


def list_behavior_attributions(
    user_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.execute(
            select(BehaviorAttribution)
            .where(BehaviorAttribution.user_id == user_id)
            .order_by(BehaviorAttribution.created_at.desc())
            .limit(limit)
        ).scalars().all()
        result = []
        for row in rows:
            payload = load_envelope(
                row.behavior_json, expect="dict"
            )
            if _hash(payload) != row.evidence_sha256:
                raise RuntimeError("行为归因证据 Hash 校验失败")
            result.append(
                {
                    "id": row.id,
                    "overrideId": row.override_id,
                    "signalDate": row.signal_date.isoformat(),
                    "labelDate": row.label_date.isoformat(),
                    "strategyReturn": row.strategy_return,
                    "humanReturn": row.human_return,
                    "returnDelta": row.return_delta,
                    "flags": payload["flags"],
                    "createdAt": row.created_at.isoformat(),
                }
            )
        return result
