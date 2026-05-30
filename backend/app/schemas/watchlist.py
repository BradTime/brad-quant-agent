"""Watchlist request bodies."""

from __future__ import annotations

from pydantic import BaseModel


class AddWatchlistRequest(BaseModel):
    code: str
    name: str = ""
    group: str = "默认分组"


class UpdateWatchlistRequest(BaseModel):
    group: str | None = None
    sortOrder: int | None = None
