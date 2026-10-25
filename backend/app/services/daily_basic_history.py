"""Immutable fixed-pool Tushare daily valuation history."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import insert, select

from app.core.dtutil import parse_date
from app.core.tz import MARKET_TZ
from app.db.session import SessionLocal
from app.models.extra import TushareDailyBasic
from app.models.ingestion import DailyBasicHistorySnapshot
from app.models.market import Instrument

AVAILABILITY_POLICY = "trade-date-17:00-asia-shanghai"
SOURCE = "tushare:daily_basic"
_TEN_THOUSAND = Decimal("10000")


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _decimal(value: Any, *, required: bool = False) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValueError("daily_basic 缺少必需数值")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("daily_basic 包含无效数值") from exc
    if not result.is_finite():
        raise ValueError("daily_basic 包含非有限数值")
    return result.quantize(Decimal("0.000001"))


def normalize_rows(
    raw_rows: list[dict[str, Any]],
    *,
    codes: list[str],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    allowed = set(codes)
    normalized: dict[tuple[str, date], dict[str, Any]] = {}
    for raw in raw_rows:
        code = str(raw.get("ts_code") or "").strip().upper()
        trade_date = parse_date(raw.get("trade_date"))
        if code not in allowed or trade_date is None:
            raise ValueError("daily_basic 返回了范围外或无日期记录")
        if not start <= trade_date <= end:
            raise ValueError("daily_basic 返回日期超出请求范围")
        total_mv = _decimal(raw.get("total_mv"), required=True)
        assert total_mv is not None
        row = {
            "code": code,
            "trade_date": trade_date,
            "available_at": datetime.combine(
                trade_date, time(17, 0), tzinfo=MARKET_TZ
            ).astimezone(UTC),
            "pe_ttm": _decimal(raw.get("pe_ttm")),
            "pb": _decimal(raw.get("pb")),
            "ps_ttm": _decimal(raw.get("ps_ttm")),
            "dv_ttm": _decimal(raw.get("dv_ttm")),
            "total_mv": (
                total_mv * _TEN_THOUSAND
            ).quantize(Decimal("0.0001")),
            "source": SOURCE,
        }
        key = (code, trade_date)
        if key in normalized and normalized[key] != row:
            raise ValueError(f"{code} {trade_date} daily_basic 重复冲突")
        normalized[key] = row
    return [
        normalized[key]
        for key in sorted(normalized, key=lambda item: (item[1], item[0]))
    ]


def persist_snapshot(
    *,
    raw_rows: list[dict[str, Any]],
    codes: list[str],
    start: date,
    end: date,
    as_of_date: date,
) -> dict[str, Any]:
    canonical_codes = sorted(set(codes))
    if not canonical_codes or len(canonical_codes) != len(codes):
        raise ValueError("daily_basic 固定股票池不能为空或重复")
    rows = normalize_rows(
        raw_rows, codes=canonical_codes, start=start, end=end
    )
    codes_sha256 = _sha256(canonical_codes)
    content_payload = [
        {
            key: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else str(value)
                if isinstance(value, Decimal)
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    ]
    content_sha256 = _sha256(content_payload)
    snapshot_id = _sha256(
        {
            "asOfDate": as_of_date.isoformat(),
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "codesSha256": codes_sha256,
            "contentSha256": content_sha256,
            "availabilityPolicy": AVAILABILITY_POLICY,
        }
    )
    with SessionLocal.begin() as session:
        known_codes = set(
            session.scalars(
                select(Instrument.code).where(
                    Instrument.code.in_(canonical_codes)
                )
            )
        )
        missing = sorted(set(canonical_codes) - known_codes)
        if missing:
            raise ValueError(
                f"{missing[0]} 等 {len(missing)} 个标的不存在"
            )
        existing = session.scalar(
            select(DailyBasicHistorySnapshot).where(
                DailyBasicHistorySnapshot.as_of_date == as_of_date,
                DailyBasicHistorySnapshot.start_date == start,
                DailyBasicHistorySnapshot.end_date == end,
                DailyBasicHistorySnapshot.codes_sha256 == codes_sha256,
                DailyBasicHistorySnapshot.availability_policy
                == AVAILABILITY_POLICY,
            )
        )
        if existing is not None:
            if existing.id != snapshot_id:
                raise ValueError("同范围 daily_basic 快照内容发生变化")
            return snapshot_summary(existing)
        if not rows:
            raise ValueError("daily_basic 快照不能为空")
        session.execute(
            insert(TushareDailyBasic),
            [{**row, "snapshot_id": snapshot_id} for row in rows],
        )
        session.execute(
            insert(DailyBasicHistorySnapshot).values(
                id=snapshot_id,
                as_of_date=as_of_date,
                start_date=start,
                end_date=end,
                code_count=len(canonical_codes),
                row_count=len(rows),
                codes_sha256=codes_sha256,
                content_sha256=content_sha256,
                availability_policy=AVAILABILITY_POLICY,
            )
        )
    with SessionLocal() as session:
        return snapshot_summary(
            session.get(DailyBasicHistorySnapshot, snapshot_id)
        )


def snapshot_summary(row: DailyBasicHistorySnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "asOfDate": row.as_of_date.isoformat(),
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat(),
        "codeCount": row.code_count,
        "rowCount": row.row_count,
        "codesSha256": row.codes_sha256,
        "contentSha256": row.content_sha256,
        "availabilityPolicy": row.availability_policy,
    }


def latest_snapshot_id(
    session,
    *,
    codes: list[str],
    start: date,
    end: date,
) -> str:
    row = session.scalar(
        select(DailyBasicHistorySnapshot)
        .where(
            DailyBasicHistorySnapshot.codes_sha256
            == _sha256(sorted(set(codes))),
            DailyBasicHistorySnapshot.start_date <= start,
            DailyBasicHistorySnapshot.end_date >= end,
            DailyBasicHistorySnapshot.availability_policy
            == AVAILABILITY_POLICY,
        )
        .order_by(
            DailyBasicHistorySnapshot.fetched_at.desc(),
            DailyBasicHistorySnapshot.id.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise ValueError("缺少覆盖训练范围的固定 daily_basic 快照")
    return row.id


def rows_by_code_date_in_session(
    session,
    *,
    snapshot_id: str,
    codes: list[str],
    start: date,
    end: date,
) -> dict[str, dict[date, dict[str, float | None]]]:
    rows = session.scalars(
        select(TushareDailyBasic).where(
            TushareDailyBasic.snapshot_id == snapshot_id,
            TushareDailyBasic.code.in_(codes),
            TushareDailyBasic.trade_date >= start,
            TushareDailyBasic.trade_date <= end,
        )
    ).all()
    result = {code: {} for code in codes}
    for row in rows:
        result[row.code][row.trade_date] = {
            "peTtm": float(row.pe_ttm) if row.pe_ttm is not None else None,
            "pb": float(row.pb) if row.pb is not None else None,
            "psTtm": float(row.ps_ttm) if row.ps_ttm is not None else None,
            "dividendTtm": (
                float(row.dv_ttm) if row.dv_ttm is not None else None
            ),
            "totalMarketValue": float(row.total_mv),
        }
    return result
