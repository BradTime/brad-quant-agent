"""Immutable fixed-pool Tushare moneyflow history for prediction features."""

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
from app.models.extra import TushareMoneyflowDaily
from app.models.ingestion import MoneyflowHistorySnapshot
from app.models.market import Instrument

AVAILABILITY_POLICY = "trade-date-17:00-asia-shanghai"
SOURCE = "tushare:moneyflow"
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


def _yuan(value: Any, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value)) * _TEN_THOUSAND
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"moneyflow {field} 不是有效金额") from exc
    if not result.is_finite():
        raise ValueError(f"moneyflow {field} 不是有限金额")
    return result.quantize(Decimal("0.0001"))


def _net(raw: dict[str, Any], buy: str, sell: str) -> Decimal:
    return _yuan(raw.get(buy), field=buy) - _yuan(
        raw.get(sell), field=sell
    )


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
            raise ValueError("moneyflow 返回了范围外或无日期记录")
        if not start <= trade_date <= end:
            raise ValueError("moneyflow 返回日期超出请求范围")
        key = (code, trade_date)
        row = {
            "code": code,
            "trade_date": trade_date,
            "available_at": datetime.combine(
                trade_date, time(17, 0), tzinfo=MARKET_TZ
            ).astimezone(UTC),
            "net_amount": _yuan(
                raw.get("net_mf_amount"), field="net_mf_amount"
            ),
            "small_net_amount": _net(
                raw, "buy_sm_amount", "sell_sm_amount"
            ),
            "medium_net_amount": _net(
                raw, "buy_md_amount", "sell_md_amount"
            ),
            "large_net_amount": _net(
                raw, "buy_lg_amount", "sell_lg_amount"
            ),
            "extra_large_net_amount": _net(
                raw, "buy_elg_amount", "sell_elg_amount"
            ),
            "source": SOURCE,
        }
        if key in normalized and normalized[key] != row:
            raise ValueError(f"{code} {trade_date} moneyflow 重复冲突")
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
        raise ValueError("moneyflow 固定股票池不能为空或重复")
    if end < start:
        raise ValueError("moneyflow 结束日期早于开始日期")
    rows = normalize_rows(
        raw_rows, codes=canonical_codes, start=start, end=end
    )
    with SessionLocal.begin() as session:
        known_codes = set(
            session.scalars(
                select(Instrument.code).where(
                    Instrument.code.in_(canonical_codes)
                )
            )
        )
        missing_codes = sorted(set(canonical_codes) - known_codes)
        if missing_codes:
            raise ValueError(
                f"{missing_codes[0]} 等 {len(missing_codes)} 个标的不存在"
            )
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
        codes_sha256 = _sha256(canonical_codes)
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
        existing = session.scalar(
            select(MoneyflowHistorySnapshot).where(
                MoneyflowHistorySnapshot.as_of_date == as_of_date,
                MoneyflowHistorySnapshot.start_date == start,
                MoneyflowHistorySnapshot.end_date == end,
                MoneyflowHistorySnapshot.codes_sha256 == codes_sha256,
            )
        )
        if existing is not None:
            if existing.id != snapshot_id:
                raise ValueError("同范围 moneyflow 快照内容发生变化")
            return snapshot_summary(existing)
        if not rows:
            raise ValueError("moneyflow 快照不能为空")
        session.execute(
            insert(TushareMoneyflowDaily),
            [{**row, "snapshot_id": snapshot_id} for row in rows],
        )
        session.execute(
            insert(MoneyflowHistorySnapshot).values(
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
            session.get(MoneyflowHistorySnapshot, snapshot_id)
        )


def snapshot_summary(row: MoneyflowHistorySnapshot) -> dict[str, Any]:
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
    codes_sha256 = _sha256(sorted(set(codes)))
    row = session.scalar(
        select(MoneyflowHistorySnapshot)
        .where(
            MoneyflowHistorySnapshot.codes_sha256 == codes_sha256,
            MoneyflowHistorySnapshot.start_date <= start,
            MoneyflowHistorySnapshot.end_date >= end,
        )
        .order_by(
            MoneyflowHistorySnapshot.fetched_at.desc(),
            MoneyflowHistorySnapshot.id.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise ValueError("缺少覆盖训练范围的固定 moneyflow 快照")
    return row.id


def rows_by_code_date_in_session(
    session,
    *,
    snapshot_id: str,
    codes: list[str],
    start: date,
    end: date,
) -> dict[str, dict[date, dict[str, float]]]:
    rows = session.scalars(
        select(TushareMoneyflowDaily).where(
            TushareMoneyflowDaily.snapshot_id == snapshot_id,
            TushareMoneyflowDaily.code.in_(codes),
            TushareMoneyflowDaily.trade_date >= start,
            TushareMoneyflowDaily.trade_date <= end,
        )
    ).all()
    result = {code: {} for code in codes}
    for row in rows:
        result[row.code][row.trade_date] = {
            "netAmount": float(row.net_amount),
            "largeNetAmount": float(
                row.large_net_amount + row.extra_large_net_amount
            ),
        }
    return result
