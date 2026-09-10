"""Operator-triggered trustworthy M3 training orchestration."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import select

from app.backtest import runner
from app.backtest.universe import expected_session_dates
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.universe import UniverseSnapshotDaily
from app.prediction.features import build_daily_examples, build_latest_features
from app.prediction.modeling import ModelProvider
from app.prediction.regime import REGIME_RULES_VERSION, classify_market_regime
from app.services import prediction_registry, universe_membership


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
                for value in ordered_dates[index - 59 : index + 1]
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


def train_from_database(
    *,
    version: str,
    provider: ModelProvider,
    codes: list[str],
    start: date,
    end: date,
    user_id: str | None = None,
) -> dict:
    duration = (end - start).days
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
    examples = [
        row
        for row in build_daily_examples(
            bars_by_code,
            eligible_by_date=eligible_by_date,
        )
        if start <= row.signal_date <= end
    ]
    regimes, regime_evidence_sha256 = _regimes(start, end)
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
            regime_evidence_sha256 + universe_evidence_sha256
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
    )


def infer_from_database(
    *,
    signal_date: date,
    codes: list[str],
) -> list[dict]:
    features = build_inference_features_from_database(
        signal_date=signal_date, codes=codes
    )
    return prediction_registry.infer_and_store(features)


def infer_model_from_database(
    *,
    model_run_id: str,
    signal_date: date,
    codes: list[str],
) -> list[dict]:
    features = build_inference_features_from_database(
        signal_date=signal_date, codes=codes
    )
    return prediction_registry.infer_model_and_store(
        model_run_id, features
    )


def build_inference_features_from_database(
    *,
    signal_date: date,
    codes: list[str],
) -> list:
    if not 1 <= len(codes) <= 20:
        raise ValueError("单次预测标的数量必须在 1 到 20")
    eligible = set(universe_membership.eligible_codes(signal_date))
    requested = set(codes)
    if not requested <= eligible:
        unavailable = sorted(requested - eligible)
        raise ValueError(
            f"{unavailable[0]} 等 {len(unavailable)} 个标的不在当日 PIT 股票池"
        )
    bars_by_code = {}
    start = (signal_date - timedelta(days=60)).isoformat()
    for code in codes:
        bars, quality = runner.load_bars_with_quality(
            code,
            "1d",
            start,
            signal_date.isoformat(),
        )
        if quality != "full":
            raise ValueError(f"{code} 预测日线或复权质量不是 full")
        bars_by_code[code] = bars
    features = build_latest_features(
        bars_by_code,
        signal_date=signal_date,
        eligible_codes=requested,
    )
    if len(features) != len(codes):
        raise ValueError("部分标的缺少完整预测特征")
    return features
