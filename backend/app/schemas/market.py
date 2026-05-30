"""Market request bodies (screener)."""

from __future__ import annotations

from pydantic import BaseModel


class ScreenRequest(BaseModel):
    # 过滤条件（均可选）：priceMin/priceMax/changePercentMin/changePercentMax/
    # volumeMin/volumeMax/amountMin/amountMax/keyword
    filters: dict | None = None
    limit: int = 50
    sortBy: str = "changePercent"
    sortOrder: str = "desc"
