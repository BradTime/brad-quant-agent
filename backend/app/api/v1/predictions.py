"""Trusted champion forecast reads and admin-only promotion."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_admin
from app.core.response import success
from app.models.user import User
from app.providers.symbols import normalize_a_share_code
from app.services import prediction_registry

router = APIRouter()


@router.get("")
def latest_prediction(
    code: str,
    asOf: date | None = Query(default=None),
    _user: User = Depends(get_current_user),
) -> dict:
    try:
        canonical = normalize_a_share_code(code)
        result = prediction_registry.get_prediction(canonical, as_of=asOf)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="暂无可信预测")
    return success(result)


@router.post("/models/{run_id}/promote")
def promote_model(
    run_id: str,
    _admin: User = Depends(require_admin),
) -> dict:
    try:
        result = prediction_registry.promote_candidate(
            run_id,
            promoted_by_user_id=str(_admin.id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)
