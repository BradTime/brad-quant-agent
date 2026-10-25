from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.core.response import success
from app.models.user import User
from app.providers.symbols import normalize_a_share_codes
from app.schemas.evolution import (
    EvolutionEnrollRequest,
    EvolutionEvaluateRequest,
)
from app.services import evolution

router = APIRouter()


@router.get("")
def programs(
    limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(require_admin),
) -> dict:
    return success({"items": evolution.list_programs(limit=limit)})


@router.get("/{program_id}")
def program_detail(
    program_id: str,
    _: User = Depends(require_admin),
) -> dict:
    try:
        return success(evolution.get(program_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/models/{model_run_id}/enroll")
def enroll_model(
    model_run_id: str,
    body: EvolutionEnrollRequest,
    admin: User = Depends(require_admin),
) -> dict:
    try:
        return success(
            evolution.enroll(
                model_run_id,
                codes=normalize_a_share_codes(body.codes),
                created_by_user_id=str(admin.id),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{program_id}/evaluate")
def evaluate_program(
    program_id: str,
    body: EvolutionEvaluateRequest,
    _: User = Depends(require_admin),
) -> dict:
    try:
        return success(
            evolution.evaluate_day(
                program_id, signal_date=body.signalDate
            )
        )
    except evolution.EvolutionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{program_id}/commit")
def commit_program_signal(
    program_id: str,
    body: EvolutionEvaluateRequest,
    _: User = Depends(require_admin),
) -> dict:
    try:
        return success(
            evolution.commit_signal(
                program_id, signal_date=body.signalDate
            )
        )
    except evolution.EvolutionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
