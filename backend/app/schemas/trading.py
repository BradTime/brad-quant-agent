"""模拟交易请求 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    side: Literal["buy", "sell"]
    type: Literal["limit", "market"]
    qty: int = Field(gt=0)
    # 限价单需提供价格；市价单可省略
    price: float | None = Field(default=None, gt=0)
