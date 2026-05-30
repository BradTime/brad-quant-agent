"""Watchlist endpoints (自选股) — all require auth, isolated by user_id."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.response import success
from app.models.user import User
from app.schemas.watchlist import AddWatchlistRequest, UpdateWatchlistRequest
from app.services import watchlist

router = APIRouter()


@router.get("")
def get_watchlist(user: User = Depends(get_current_user)) -> dict:
    return success(watchlist.list_items(str(user.id)))


@router.get("/groups")
def get_groups(user: User = Depends(get_current_user)) -> dict:
    return success(watchlist.list_groups(str(user.id)))


@router.post("")
def add(body: AddWatchlistRequest, user: User = Depends(get_current_user)) -> dict:
    return success(watchlist.add_item(str(user.id), body.code, body.name, body.group))


@router.patch("/{code}")
def patch(
    code: str, body: UpdateWatchlistRequest, user: User = Depends(get_current_user)
) -> dict:
    ok = watchlist.update_item(str(user.id), code, body.group, body.sortOrder)
    return success({"updated": ok})


@router.delete("/{code}")
def remove(code: str, user: User = Depends(get_current_user)) -> dict:
    ok = watchlist.remove_item(str(user.id), code)
    return success({"removed": ok})
