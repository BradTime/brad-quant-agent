"""Watchlist service — CRUD over ``WatchlistItem`` with user isolation.

Items are returned enriched with the latest cached quote (price/change) so the
frontend can render a usable list without a second round-trip. Quotes come from
the in-memory cache (cold-start triggers one live fetch via the market service).
"""

from __future__ import annotations

from sqlalchemy import delete, select, update

from app.db.session import SessionLocal
from app.models.watchlist import WatchlistItem
from app.providers import symbols
from app.services import market


def _canonical(code: str) -> str:
    return code if "." in code else symbols.to_canonical(symbols.to_six(code))


def list_items(user_id: str) -> list[dict]:
    with SessionLocal() as session:
        stmt = (
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(WatchlistItem.group_name, WatchlistItem.sort_order, WatchlistItem.id)
        )
        rows = list(session.execute(stmt).scalars().all())

    # 缓存优先（不触发实时拉取）；命中不到的用 DB 最近收盘兜底，保证列表永不因数据源限流而阻塞。
    quotes = market.quotes_map_snapshot()

    out: list[dict] = []
    for r in rows:
        q = quotes.get(r.code) or market.get_cached_or_last_quote(r.code)
        out.append(
            {
                "code": r.code,
                "name": r.name or (q.get("name") if q else ""),
                "group": r.group_name,
                "sortOrder": r.sort_order,
                "price": q.get("price") if q else None,
                "change": q.get("change") if q else None,
                "changePercent": q.get("changePercent") if q else None,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def list_groups(user_id: str) -> list[str]:
    with SessionLocal() as session:
        stmt = (
            select(WatchlistItem.group_name)
            .where(WatchlistItem.user_id == user_id)
            .distinct()
        )
        groups = [g for (g,) in session.execute(stmt).all()]
    return sorted(groups) or ["默认分组"]


def add_item(user_id: str, code: str, name: str = "", group: str = "默认分组") -> dict:
    canonical = _canonical(code)
    if not name:
        # 名称走标的表（快速、离线），避免实时源限流时阻塞「加自选」。
        name = market.get_instrument_name(canonical)
    with SessionLocal() as session:
        existing = session.execute(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id, WatchlistItem.code == canonical
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.group_name = group or existing.group_name
            if name:
                existing.name = name
            session.commit()
            return {"code": canonical, "added": False}
        max_sort = session.execute(
            select(WatchlistItem.sort_order)
            .where(WatchlistItem.user_id == user_id, WatchlistItem.group_name == group)
            .order_by(WatchlistItem.sort_order.desc())
            .limit(1)
        ).scalar_one_or_none()
        session.add(
            WatchlistItem(
                user_id=user_id,
                code=canonical,
                name=name,
                group_name=group or "默认分组",
                sort_order=(max_sort or 0) + 1,
            )
        )
        session.commit()
    return {"code": canonical, "added": True}


def remove_item(user_id: str, code: str) -> bool:
    canonical = _canonical(code)
    with SessionLocal() as session:
        result = session.execute(
            delete(WatchlistItem).where(
                WatchlistItem.user_id == user_id, WatchlistItem.code == canonical
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0


def update_item(
    user_id: str, code: str, group: str | None = None, sort_order: int | None = None
) -> bool:
    canonical = _canonical(code)
    values: dict = {}
    if group is not None:
        values["group_name"] = group
    if sort_order is not None:
        values["sort_order"] = sort_order
    if not values:
        return False
    with SessionLocal() as session:
        result = session.execute(
            update(WatchlistItem)
            .where(WatchlistItem.user_id == user_id, WatchlistItem.code == canonical)
            .values(**values)
        )
        session.commit()
        return (result.rowcount or 0) > 0


def is_watched(user_id: str, code: str) -> bool:
    canonical = _canonical(code)
    with SessionLocal() as session:
        return (
            session.execute(
                select(WatchlistItem.id).where(
                    WatchlistItem.user_id == user_id, WatchlistItem.code == canonical
                )
            ).first()
            is not None
        )
