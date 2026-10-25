"""Operator-triggered trustworthy M3 training orchestration."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.backtest import runner
from app.backtest.universe import expected_session_dates
from app.core.config import settings
from app.core.json_payload import load_envelope
from app.db.session import SessionLocal
from app.models.prediction import PredictionModelRun
from app.models.universe import UniverseSnapshotDaily
from app.prediction.features import build_daily_examples, build_latest_features
from app.prediction.modeling import ModelProvider
from app.prediction.regime import REGIME_RULES_VERSION, classify_market_regime
from app.services import (
    industry_membership,
    moneyflow_history,
    prediction_registry,
    universe_membership,
)


def _consecutive_market_dates(days: list[date]) -> bool:
    return bool(
        days
        and expected_session_dates(days[0], days[-1])
        == tuple(day.isoformat() for day in days)
    )


def _regimes(
    start: date,
    end: date,
) -> tuple[dict[date, str], str]:
    benchmark, quality = runner.load_benchmark_with_quality(
        (start - timedelta(days=120)).isoformat(),
        end.isoformat(),
    )
    if quality != "full":
        raise ValueError("沪深300训练基准数据或复权质量不完整")
    closes_by_date = {bar.date: bar.close for bar in benchmark}
    with SessionLocal() as session:
        snapshots = session.execute(
            select(UniverseSnapshotDaily).where(
                UniverseSnapshotDaily.trade_date >= start,
                UniverseSnapshotDaily.trade_date <= end,
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION,
            )
        ).scalars().all()
    snapshots_by_date = {row.trade_date: row for row in snapshots}
    ordered_dates = sorted(closes_by_date)
    regimes: dict[date, str] = {}
    for index, day in enumerate(ordered_dates):
        if day < start or day > end or index < 59:
            continue
        regime_dates = ordered_dates[index - 59 : index + 1]
        if not _consecutive_market_dates(regime_dates):
            continue
        snapshot = snapshots_by_date.get(day)
        if (
            snapshot is None
            or snapshot.advancing_count is None
            or snapshot.declining_count is None
            or snapshot.advancing_count + snapshot.declining_count <= 0
        ):
            continue
        breadth = snapshot.advancing_count / (
            snapshot.advancing_count + snapshot.declining_count
        )
        result = classify_market_regime(
            index_closes=[
                closes_by_date[value]
                for value in regime_dates
            ],
            market_breadth=breadth,
        )
        regimes[day] = result["regime"]
    evidence = {
        "benchmark": [
            {
                "date": (
                    bar.date.date().isoformat()
                    if hasattr(bar.date, "date")
                    else bar.date.isoformat()
                ),
                "close": bar.close,
            }
            for bar in benchmark
        ],
        "universeSnapshots": [
            {
                "date": row.trade_date.isoformat(),
                "rulesVersion": row.rules_version,
                "membershipSha256": row.membership_sha256,
                "advancing": row.advancing_count,
                "declining": row.declining_count,
            }
            for row in sorted(
                snapshots, key=lambda item: item.trade_date
            )
        ],
        "regimeRulesVersion": REGIME_RULES_VERSION,
        "regimes": {
            day.isoformat(): regime
            for day, regime in sorted(regimes.items())
        },
    }
    evidence_sha256 = hashlib.sha256(
        json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return regimes, evidence_sha256


def _market_features(
    start: date,
    end: date,
    regimes: dict[date, str],
) -> dict[date, dict[str, float]]:
    benchmark, quality = runner.load_benchmark_with_quality(
        (start - timedelta(days=120)).isoformat(),
        end.isoformat(),
    )
    if quality != "full":
        raise ValueError("沪深300市场特征数据或复权质量不完整")
    bars_by_date = {bar.date: bar for bar in benchmark}
    ordered_dates = sorted(bars_by_date)
    with SessionLocal() as session:
        snapshots = session.execute(
            select(UniverseSnapshotDaily).where(
                UniverseSnapshotDaily.trade_date >= start,
                UniverseSnapshotDaily.trade_date <= end,
                UniverseSnapshotDaily.rules_version
                == universe_membership.RULES_VERSION,
            )
        ).scalars().all()
    snapshot_by_date = {row.trade_date: row for row in snapshots}
    features = {}
    for index, day in enumerate(ordered_dates):
        if day < start or day > end or index < 20:
            continue
        market_dates = ordered_dates[index - 20 : index + 1]
        if not _consecutive_market_dates(market_dates):
            continue
        snapshot = snapshot_by_date.get(day)
        if (
            snapshot is None
            or snapshot.advancing_count is None
            or snapshot.declining_count is None
            or snapshot.advancing_count + snapshot.declining_count <= 0
        ):
            continue
        closes = [
            bars_by_date[value].close
            for value in market_dates
        ]
        returns = [
            closes[position] / closes[position - 1] - 1
            for position in range(1, len(closes))
        ]
        average = sum(returns) / len(returns)
        volatility = math.sqrt(
            sum((value - average) ** 2 for value in returns)
            / len(returns)
        )
        breadth = snapshot.advancing_count / (
            snapshot.advancing_count + snapshot.declining_count
        )
        regime = regimes.get(day)
        if regime is None:
            continue
        features[day] = {
            "marketReturn1": closes[-1] / closes[-2] - 1,
            "marketReturn5": closes[-1] / closes[-6] - 1,
            "marketReturn20": closes[-1] / closes[0] - 1,
            "marketVolatility20": volatility,
            "marketBreadth": breadth - 0.5,
            "marketBreadthImbalance": (
                snapshot.advancing_count - snapshot.declining_count
            )
            / (
                snapshot.advancing_count + snapshot.declining_count
            ),
            "regimeBull": float(regime == "bull"),
            "regimeBear": float(regime == "bear"),
            "regimeRange": float(regime == "range"),
            "regimeRiskOff": float(regime == "risk_off"),
        }
    return features


def train_from_database(
    *,
    version: str,
    provider: ModelProvider,
    codes: list[str],
    start: date,
    end: date,
    user_id: str | None = None,
    publication_guard: Callable[[Any], bool] | None = None,
) -> dict:
    feature_start = max(start, industry_membership.EFFECTIVE_FLOOR)
    duration = (end - feature_start).days
    if not 365 * 3 <= duration <= 366 * 5:
        raise ValueError("训练窗口必须在 3 到 5 年")
    if not 1 <= len(codes) <= 20:
        raise ValueError("训练标的数量必须在 1 到 20")
    expected_dates = set(expected_session_dates(start, end))
    eligible_by_date = universe_membership.eligible_map(codes, start, end)
    missing_dates = sorted(expected_dates - set(eligible_by_date))
    if missing_dates:
        raise ValueError(
            f"PIT 股票池缺少 {missing_dates[0]} 等 {len(missing_dates)} 日"
        )
    bars_by_code = {}
    load_start = (start - timedelta(days=60)).isoformat()
    for code in codes:
        bars, quality = runner.load_bars_with_quality(
            code,
            "1d",
            load_start,
            end.isoformat(),
        )
        if quality != "full":
            raise ValueError(f"{code} 训练日线或复权质量不是 full")
        bars_by_code[code] = bars
    regimes, regime_evidence_sha256 = _regimes(start, end)
    market_features = _market_features(start, end, regimes)
    feature_dates = sorted(
        day
        for day in market_features
        if feature_start <= day <= end
    )
    with SessionLocal() as session:
        industry_snapshot_id = industry_membership.latest_snapshot_id(
            session
        )
        industry_by_date = (
            industry_membership.industry_map_by_date_in_session(
                session,
                codes,
                feature_dates,
                snapshot_id=industry_snapshot_id,
            )
        )
        warmup_dates = [
            date.fromisoformat(value)
            for value in expected_session_dates(
                feature_start - timedelta(days=60), feature_start
            )
        ]
        flow_start = warmup_dates[-21]
        moneyflow_snapshot_id = moneyflow_history.latest_snapshot_id(
            session,
            codes=codes,
            start=flow_start,
            end=end,
        )
        moneyflow_by_code_date = (
            moneyflow_history.rows_by_code_date_in_session(
                session,
                snapshot_id=moneyflow_snapshot_id,
                codes=codes,
                start=flow_start,
                end=end,
            )
        )
    examples = [
        row
        for row in build_daily_examples(
            bars_by_code,
            eligible_by_date=eligible_by_date,
            market_features_by_date=market_features,
            industry_by_date=industry_by_date,
            moneyflow_by_code_date=moneyflow_by_code_date,
        )
        if feature_start <= row.signal_date <= end
    ]
    universe_evidence_sha256 = hashlib.sha256(
        json.dumps(
            {
                day: list(day_codes)
                for day, day_codes in sorted(eligible_by_date.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    evidence_sha256 = hashlib.sha256(
        (
            regime_evidence_sha256
            + universe_evidence_sha256
            + industry_snapshot_id
            + moneyflow_snapshot_id
        ).encode()
    ).hexdigest()
    return prediction_registry.register_candidate(
        user_id,
        version=version,
        provider=provider,
        examples=examples,
        regime_by_date=regimes,
        evidence_sha256=evidence_sha256,
        minimum_train_dates=252,
        validation_dates=63,
        embargo_dates=settings.prediction_embargo_sessions,
        max_folds=settings.prediction_cv_folds,
        publication_guard=publication_guard,
        feature_universe_codes=codes,
        feature_industry_snapshot_id=industry_snapshot_id,
        feature_moneyflow_snapshot_id=moneyflow_snapshot_id,
    )


def infer_from_database(
    *,
    signal_date: date,
    codes: list[str],
) -> list[dict]:
    with SessionLocal() as session:
        champion = prediction_registry._champion(session)
        metrics = load_envelope(
            champion.metrics_json, expect="dict"
        )
        rank_universe_codes = metrics.get("featureUniverseCodes")
        industry_snapshot_id = metrics.get(
            "featureIndustrySnapshotId"
        )
        moneyflow_snapshot_id = metrics.get(
            "featureMoneyflowSnapshotId"
        )
    if (
        not isinstance(rank_universe_codes, list)
        or not rank_universe_codes
    ):
        if champion.feature_schema_version == "daily-pit-v1":
            rank_universe_codes = codes
        else:
            raise ValueError("Champion 缺少固定特征股票池")
    if (
        champion.feature_schema_version == "daily-pit-v4"
        and not isinstance(industry_snapshot_id, str)
    ):
        raise ValueError("Champion 缺少固定行业快照")
    if (
        champion.feature_schema_version == "daily-pit-v5"
        and (
            not isinstance(industry_snapshot_id, str)
            or not isinstance(moneyflow_snapshot_id, str)
        )
    ):
        raise ValueError("Champion 缺少固定行业或资金流快照")
    features = build_inference_features_from_database(
        signal_date=signal_date,
        codes=codes,
        rank_universe_codes=rank_universe_codes,
        industry_snapshot_id=(
            industry_snapshot_id
            if isinstance(industry_snapshot_id, str)
            else None
        ),
        moneyflow_snapshot_id=(
            moneyflow_snapshot_id
            if isinstance(moneyflow_snapshot_id, str)
            else None
        ),
    )
    return prediction_registry.infer_model_and_store(
        champion.id, features
    )


def infer_model_from_database(
    *,
    model_run_id: str,
    signal_date: date,
    codes: list[str],
) -> list[dict]:
    with SessionLocal() as session:
        model = session.get(PredictionModelRun, model_run_id)
        if model is None:
            raise ValueError("预测模型不存在")
        metrics = load_envelope(model.metrics_json, expect="dict")
        rank_universe_codes = metrics.get("featureUniverseCodes")
        industry_snapshot_id = metrics.get(
            "featureIndustrySnapshotId"
        )
        moneyflow_snapshot_id = metrics.get(
            "featureMoneyflowSnapshotId"
        )
    if not isinstance(rank_universe_codes, list):
        rank_universe_codes = (
            codes
            if model.feature_schema_version == "daily-pit-v1"
            else []
        )
    if not rank_universe_codes:
        raise ValueError("模型缺少固定特征股票池")
    if (
        model.feature_schema_version == "daily-pit-v4"
        and not isinstance(industry_snapshot_id, str)
    ):
        raise ValueError("模型缺少固定行业快照")
    if (
        model.feature_schema_version == "daily-pit-v5"
        and (
            not isinstance(industry_snapshot_id, str)
            or not isinstance(moneyflow_snapshot_id, str)
        )
    ):
        raise ValueError("模型缺少固定行业或资金流快照")
    features = build_inference_features_from_database(
        signal_date=signal_date,
        codes=codes,
        rank_universe_codes=rank_universe_codes,
        industry_snapshot_id=(
            industry_snapshot_id
            if isinstance(industry_snapshot_id, str)
            else None
        ),
        moneyflow_snapshot_id=(
            moneyflow_snapshot_id
            if isinstance(moneyflow_snapshot_id, str)
            else None
        ),
    )
    return prediction_registry.infer_model_and_store(
        model_run_id, features
    )


def build_inference_features_from_database(
    *,
    signal_date: date,
    codes: list[str],
    rank_universe_codes: list[str] | None = None,
    industry_snapshot_id: str | None = None,
    moneyflow_snapshot_id: str | None = None,
) -> list:
    if not 1 <= len(codes) <= 20:
        raise ValueError("单次预测标的数量必须在 1 到 20")
    rank_codes = sorted(set(rank_universe_codes or codes))
    if not set(codes) <= set(rank_codes):
        raise ValueError("推理标的必须属于固定截面排名股票池")
    eligible = set(universe_membership.eligible_codes(signal_date))
    requested = set(codes)
    if not requested <= eligible:
        unavailable = sorted(requested - eligible)
        raise ValueError(
            f"{unavailable[0]} 等 {len(unavailable)} 个标的不在当日 PIT 股票池"
        )
    bars_by_code = {}
    start = (signal_date - timedelta(days=60)).isoformat()
    eligible_rank_codes = set(rank_codes) & eligible
    for code in sorted(eligible_rank_codes):
        bars, quality = runner.load_bars_with_quality(
            code,
            "1d",
            start,
            signal_date.isoformat(),
        )
        if quality != "full":
            raise ValueError(f"{code} 预测日线或复权质量不是 full")
        bars_by_code[code] = bars
    inference_regimes, _ = _regimes(signal_date, signal_date)
    market_features = _market_features(
        signal_date,
        signal_date,
        inference_regimes,
    ).get(signal_date)
    if market_features is None:
        raise ValueError("决策日缺少完整 PIT 市场特征")
    industry_by_code = None
    if industry_snapshot_id is not None:
        with SessionLocal() as session:
            industry_by_code = (
                industry_membership.industries_asof_in_session(
                    session,
                    sorted(eligible_rank_codes),
                    signal_date,
                    snapshot_id=industry_snapshot_id,
                )
            )
    moneyflow_by_code_date = None
    if moneyflow_snapshot_id is not None:
        flow_start_dates = [
            date.fromisoformat(value)
            for value in expected_session_dates(
                signal_date - timedelta(days=60), signal_date
            )
        ]
        flow_start = flow_start_dates[-21]
        with SessionLocal() as session:
            moneyflow_by_code_date = (
                moneyflow_history.rows_by_code_date_in_session(
                    session,
                    snapshot_id=moneyflow_snapshot_id,
                    codes=sorted(eligible_rank_codes),
                    start=flow_start,
                    end=signal_date,
                )
            )
    features = build_latest_features(
        bars_by_code,
        signal_date=signal_date,
        eligible_codes=eligible_rank_codes,
        market_features=market_features,
        industry_by_code=industry_by_code,
        moneyflow_by_code_date=moneyflow_by_code_date,
    )
    requested_features = [
        feature for feature in features if feature.code in requested
    ]
    if len(requested_features) != len(codes):
        raise ValueError("部分标的缺少完整预测特征")
    return requested_features
