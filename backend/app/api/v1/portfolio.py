"""M3 deterministic regime and portfolio-allocation previews."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.response import success
from app.models.user import User
from app.prediction.regime import classify_market_regime
from app.schemas.portfolio import RegimeRequest

router = APIRouter()


@router.post("/regime")
def regime(
    body: RegimeRequest,
    _user: User = Depends(get_current_user),
) -> dict:
    try:
        result = classify_market_regime(
            index_closes=body.indexCloses,
            market_breadth=body.marketBreadth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(
        {
            **result,
            "asOf": body.asOf.isoformat(),
            "authoritative": False,
            "notice": "仅规则预览；未绑定服务端行情、账户或预测，不可用于下单审批",
        }
    )
