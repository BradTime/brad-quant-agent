"""First-observed PIT industry classifications for authoritative allocation."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.tz import MARKET_TZ
from app.db.session import SessionLocal
from app.models.market import InstrumentIndustryVintage
from app.services import market


def _now() -> datetime:
    return datetime.now(UTC)


def refresh(code: str) -> dict:
    canonical = market.canonical_stock_code(code)
    with SessionLocal() as session:
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            lock_key = int.from_bytes(
                hashlib.sha256(canonical.encode()).digest()[:8],
                "big",
                signed=True,
            )
            session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        profile = market.get_stock_profile(canonical)
        industry = str(profile.get("industry") or "").strip()
        if not industry:
            raise ValueError("数据源未返回行业分类")
        observed_at = _now()
        previous = session.execute(
            select(InstrumentIndustryVintage)
            .where(InstrumentIndustryVintage.code == canonical)
            .order_by(
                InstrumentIndustryVintage.available_at.desc(),
                InstrumentIndustryVintage.id.desc(),
            )
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if previous is not None and previous.industry == industry:
            return {
                "code": canonical,
                "industry": industry,
                "vintage": previous.vintage,
                "observedAt": previous.available_at.isoformat(),
                "changed": False,
            }
        vintage = hashlib.sha256(
            (
                f"{canonical}\0{industry}\0"
                f"{previous.vintage if previous else 'initial'}"
            ).encode()
        ).hexdigest()
        insert = (
            sqlite_insert
            if dialect == "sqlite"
            else pg_insert
        )
        result = session.execute(
            insert(InstrumentIndustryVintage)
            .values(
                id=str(uuid4()),
                code=canonical,
                industry=industry,
                available_at=observed_at,
                vintage=vintage,
                source=str(profile.get("source") or "profile")[:32],
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            )
            .on_conflict_do_nothing(
                index_elements=["code", "vintage"]
            )
        )
        if result.rowcount == 0:
            winner = session.execute(
                select(InstrumentIndustryVintage).where(
                    InstrumentIndustryVintage.code == canonical,
                    InstrumentIndustryVintage.vintage == vintage,
                )
            ).scalar_one()
            return {
                "code": canonical,
                "industry": winner.industry,
                "vintage": winner.vintage,
                "observedAt": winner.available_at.isoformat(),
                "changed": False,
            }
        session.commit()
    return {
        "code": canonical,
        "industry": industry,
        "vintage": vintage,
        "observedAt": observed_at.isoformat(),
        "changed": True,
    }


def industries_asof_in_session(
    session, codes: list[str], as_of: date
) -> dict[str, str]:
    cutoff = datetime.combine(
        as_of, time.max, tzinfo=MARKET_TZ
    ).astimezone(UTC)
    rows = session.execute(
        select(InstrumentIndustryVintage)
        .where(
            InstrumentIndustryVintage.code.in_(codes),
            InstrumentIndustryVintage.available_at <= cutoff,
        )
        .order_by(
            InstrumentIndustryVintage.code,
            InstrumentIndustryVintage.available_at.desc(),
            InstrumentIndustryVintage.id.desc(),
        )
    ).scalars().all()
    result: dict[str, str] = {}
    for row in rows:
        result.setdefault(row.code, row.industry)
    missing = sorted(set(codes) - set(result))
    if missing:
        raise ValueError(
            f"{missing[0]} 等 {len(missing)} 个标的缺少 PIT 行业分类"
        )
    return result


def industry_evidence_asof_in_session(
    session, codes: list[str], as_of: date
) -> dict[str, dict[str, str]]:
    cutoff = datetime.combine(
        as_of, time.max, tzinfo=MARKET_TZ
    ).astimezone(UTC)
    rows = session.execute(
        select(InstrumentIndustryVintage)
        .where(
            InstrumentIndustryVintage.code.in_(codes),
            InstrumentIndustryVintage.available_at <= cutoff,
        )
        .order_by(
            InstrumentIndustryVintage.code,
            InstrumentIndustryVintage.available_at.desc(),
            InstrumentIndustryVintage.id.desc(),
        )
    ).scalars().all()
    result = {}
    for row in rows:
        result.setdefault(
            row.code,
            {
                "industry": row.industry,
                "vintage": row.vintage,
                "availableAt": row.available_at.isoformat(),
            },
        )
    missing = sorted(set(codes) - set(result))
    if missing:
        raise ValueError(
            f"{missing[0]} 等 {len(missing)} 个标的缺少 PIT 行业分类"
        )
    return result


def industries_asof(codes: list[str], as_of: date) -> dict[str, str]:
    with SessionLocal() as session:
        return industries_asof_in_session(session, codes, as_of)
