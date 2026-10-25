"""Immutable effective-dated SW2021 industry membership evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, time
from itertools import pairwise
from typing import Any

from sqlalchemy import and_, insert, or_, select

from app.core.dtutil import parse_date
from app.core.tz import MARKET_TZ
from app.db.session import SessionLocal
from app.models.ingestion import IndustryMembershipSnapshot
from app.models.market import Instrument, InstrumentIndustryMembershipHistory

TAXONOMY = "SW2021"
LEVEL = "L1"
# The revised taxonomy was officially introduced in December 2021. Earlier
# effective dates returned by the current API must not be treated as knowledge
# that existed under SW2021.
EFFECTIVE_FLOOR = date(2021, 12, 13)
SOURCE = "tushare:index_member_all"


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _optional_date(value: Any) -> date | None:
    return parse_date(str(value)) if value else None


def _merge_same_industry(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (row["code"], row["industry_code"], row["industry_name"])
        ].append(row)
    merged: list[dict[str, Any]] = []
    for values in grouped.values():
        ordered = sorted(values, key=lambda item: item["effective_from"])
        current = dict(ordered[0])
        for candidate in ordered[1:]:
            current_end = current["effective_to"]
            touches = (
                current_end is None
                or candidate["effective_from"].toordinal()
                <= current_end.toordinal() + 1
            )
            if not touches:
                merged.append(current)
                current = dict(candidate)
                continue
            candidate_end = candidate["effective_to"]
            if current_end is None or candidate_end is None:
                current["effective_to"] = None
                current["source_out_date"] = None
            elif candidate_end > current_end:
                current["effective_to"] = candidate_end
                current["source_out_date"] = candidate["source_out_date"]
            if candidate["source_in_date"] < current["source_in_date"]:
                current["source_in_date"] = candidate["source_in_date"]
        merged.append(current)
    return merged


def normalize_history(
    raw_rows: list[dict[str, Any]],
    *,
    known_codes: set[str],
) -> tuple[list[dict[str, Any]], int, int]:
    unique_source: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in raw_rows:
        code = str(raw.get("ts_code") or "").strip().upper()
        industry_code = str(raw.get("l1_code") or "").strip().upper()
        industry_name = str(raw.get("l1_name") or "").strip()
        source_in = _optional_date(raw.get("in_date"))
        source_out = _optional_date(raw.get("out_date"))
        if not code or not industry_code or not industry_name or source_in is None:
            raise ValueError("行业成员记录缺少代码、行业或纳入日期")
        if source_out is not None and source_out < source_in:
            raise ValueError(f"{code} 行业成员有效期倒置")
        unique_source[
            (code, industry_code, industry_name, source_in, source_out)
        ] = {
            "code": code,
            "industry_code": industry_code,
            "industry_name": industry_name,
            "source_in_date": source_in,
            "source_out_date": source_out,
        }
    normalized = []
    unknown_codes = set()
    for row in unique_source.values():
        if row["code"] not in known_codes:
            unknown_codes.add(row["code"])
            continue
        if (
            row["source_out_date"] is not None
            and row["source_out_date"] < EFFECTIVE_FLOOR
        ):
            continue
        normalized.append(
            {
                **row,
                "effective_from": max(
                    row["source_in_date"], EFFECTIVE_FLOOR
                ),
                "effective_to": row["source_out_date"],
                "source": SOURCE,
            }
        )
    merged = _merge_same_industry(normalized)
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in merged:
        by_code[row["code"]].append(row)
    for code, rows in by_code.items():
        ordered = sorted(rows, key=lambda item: item["effective_from"])
        for previous, current in pairwise(ordered):
            if previous["effective_to"] is None:
                raise ValueError(f"{code} 存在无结束日期的重叠行业记录")
            if current["effective_from"] <= previous["effective_to"]:
                raise ValueError(f"{code} 存在重叠行业记录")
    return (
        sorted(
            merged,
            key=lambda item: (
                item["code"],
                item["effective_from"],
                item["industry_code"],
            ),
        ),
        len(unique_source),
        len(unknown_codes),
    )


def persist_snapshot(
    *,
    classifications: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    as_of_date: date,
) -> dict[str, Any]:
    canonical_classes = sorted(
        (
            {
                "industryCode": str(row.get("index_code") or "").upper(),
                "industryName": str(row.get("industry_name") or "").strip(),
            }
            for row in classifications
        ),
        key=lambda item: item["industryCode"],
    )
    if len(canonical_classes) != 31 or any(
        not row["industryCode"] or not row["industryName"]
        for row in canonical_classes
    ):
        raise ValueError("SW2021 一级行业分类必须完整包含 31 项")
    classification_sha256 = _sha256(canonical_classes)
    with SessionLocal.begin() as session:
        known_codes = set(session.scalars(select(Instrument.code)))
        rows, source_count, unknown_count = normalize_history(
            raw_rows, known_codes=known_codes
        )
        class_lookup = {
            row["industryCode"]: row["industryName"]
            for row in canonical_classes
        }
        for row in rows:
            if class_lookup.get(row["industry_code"]) != row["industry_name"]:
                raise ValueError(
                    f"{row['industry_code']} 行业名称与分类目录不一致"
                )
        content_payload = [
            {
                key: (
                    value.isoformat()
                    if isinstance(value, date)
                    else value
                )
                for key, value in row.items()
            }
            for row in rows
        ]
        content_sha256 = _sha256(content_payload)
        snapshot_id = _sha256(
            {
                "taxonomy": TAXONOMY,
                "level": LEVEL,
                "asOfDate": as_of_date.isoformat(),
                "effectiveFloor": EFFECTIVE_FLOOR.isoformat(),
                "classificationSha256": classification_sha256,
                "contentSha256": content_sha256,
            }
        )
        existing = session.scalar(
            select(IndustryMembershipSnapshot).where(
                IndustryMembershipSnapshot.taxonomy == TAXONOMY,
                IndustryMembershipSnapshot.level == LEVEL,
                IndustryMembershipSnapshot.as_of_date == as_of_date,
            )
        )
        if existing is not None:
            if existing.id != snapshot_id:
                raise ValueError("同日行业成员快照内容发生变化")
            return snapshot_summary(existing)
        if not rows:
            raise ValueError("行业成员快照不能为空")
        session.execute(
            insert(InstrumentIndustryMembershipHistory),
            [{**row, "snapshot_id": snapshot_id} for row in rows],
        )
        session.execute(
            insert(IndustryMembershipSnapshot).values(
                id=snapshot_id,
                taxonomy=TAXONOMY,
                level=LEVEL,
                as_of_date=as_of_date,
                effective_floor=EFFECTIVE_FLOOR,
                source_row_count=source_count,
                persisted_row_count=len(rows),
                unknown_code_count=unknown_count,
                classification_sha256=classification_sha256,
                content_sha256=content_sha256,
            )
        )
    with SessionLocal() as session:
        return snapshot_summary(
            session.get(IndustryMembershipSnapshot, snapshot_id)
        )


def snapshot_summary(row: IndustryMembershipSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "taxonomy": row.taxonomy,
        "level": row.level,
        "asOfDate": row.as_of_date.isoformat(),
        "effectiveFloor": row.effective_floor.isoformat(),
        "sourceRows": row.source_row_count,
        "persistedRows": row.persisted_row_count,
        "unknownCodes": row.unknown_code_count,
        "classificationSha256": row.classification_sha256,
        "contentSha256": row.content_sha256,
    }


def latest_snapshot_id(
    session, *, available_on: date | None = None
) -> str:
    query = select(IndustryMembershipSnapshot).where(
        IndustryMembershipSnapshot.taxonomy == TAXONOMY,
        IndustryMembershipSnapshot.level == LEVEL,
    )
    if available_on is not None:
        cutoff = datetime.combine(
            available_on, time.max, tzinfo=MARKET_TZ
        ).astimezone(UTC)
        query = query.where(
            IndustryMembershipSnapshot.fetched_at <= cutoff
        )
    row = session.scalar(
        query.order_by(
            IndustryMembershipSnapshot.fetched_at.desc(),
            IndustryMembershipSnapshot.id.desc(),
        ).limit(1)
    )
    if row is None:
        raise ValueError("缺少 SW2021 历史行业成员快照")
    return row.id


def industries_asof_in_session(
    session,
    codes: list[str],
    as_of: date,
    *,
    snapshot_id: str,
) -> dict[str, str]:
    rows = session.scalars(
        select(InstrumentIndustryMembershipHistory).where(
            InstrumentIndustryMembershipHistory.snapshot_id == snapshot_id,
            InstrumentIndustryMembershipHistory.code.in_(codes),
            InstrumentIndustryMembershipHistory.effective_from <= as_of,
            or_(
                InstrumentIndustryMembershipHistory.effective_to.is_(None),
                InstrumentIndustryMembershipHistory.effective_to >= as_of,
            ),
        )
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.code in result:
            raise ValueError(f"{row.code} 在 {as_of} 存在多个行业")
        result[row.code] = row.industry_name
    missing = sorted(set(codes) - set(result))
    if missing:
        raise ValueError(
            f"{missing[0]} 等 {len(missing)} 个标的在 {as_of} 缺少历史行业"
        )
    return result


def industry_map_by_date_in_session(
    session,
    codes: list[str],
    dates: list[date],
    *,
    snapshot_id: str,
) -> dict[date, dict[str, str]]:
    if not dates:
        return {}
    ordered_dates = sorted(set(dates))
    if ordered_dates[0] < EFFECTIVE_FLOOR:
        raise ValueError(
            f"SW2021 行业特征不得早于 {EFFECTIVE_FLOOR.isoformat()}"
        )
    rows = session.scalars(
        select(InstrumentIndustryMembershipHistory).where(
            InstrumentIndustryMembershipHistory.snapshot_id == snapshot_id,
            InstrumentIndustryMembershipHistory.code.in_(codes),
            InstrumentIndustryMembershipHistory.effective_from
            <= ordered_dates[-1],
            or_(
                InstrumentIndustryMembershipHistory.effective_to.is_(None),
                InstrumentIndustryMembershipHistory.effective_to
                >= ordered_dates[0],
            ),
        )
    ).all()
    result: dict[date, dict[str, str]] = {}
    for day in ordered_dates:
        values: dict[str, str] = {}
        for row in rows:
            if (
                row.effective_from <= day
                and (row.effective_to is None or row.effective_to >= day)
            ):
                if row.code in values:
                    raise ValueError(f"{row.code} 在 {day} 存在多个行业")
                values[row.code] = row.industry_name
        missing = sorted(set(codes) - set(values))
        if missing:
            raise ValueError(
                f"{missing[0]} 等 {len(missing)} 个标的在 {day} "
                "缺少历史行业"
            )
        result[day] = values
    return result


def industry_evidence_asof_in_session(
    session,
    codes: list[str],
    as_of: date,
    *,
    snapshot_id: str,
) -> dict[str, dict[str, str | None]]:
    industries_asof_in_session(
        session, codes, as_of, snapshot_id=snapshot_id
    )
    rows = session.scalars(
        select(InstrumentIndustryMembershipHistory).where(
            and_(
                InstrumentIndustryMembershipHistory.snapshot_id == snapshot_id,
                InstrumentIndustryMembershipHistory.code.in_(codes),
                InstrumentIndustryMembershipHistory.effective_from <= as_of,
                or_(
                    InstrumentIndustryMembershipHistory.effective_to.is_(None),
                    InstrumentIndustryMembershipHistory.effective_to >= as_of,
                ),
            )
        )
    ).all()
    return {
        row.code: {
            "industry": row.industry_name,
            "industryCode": row.industry_code,
            "effectiveFrom": row.effective_from.isoformat(),
            "effectiveTo": (
                row.effective_to.isoformat() if row.effective_to else None
            ),
            "snapshotId": row.snapshot_id,
        }
        for row in rows
    }
