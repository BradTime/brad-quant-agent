from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.response import success
from app.models.user import User
from app.providers.symbols import normalize_a_share_codes
from app.schemas.decision import DecisionRunRequest
from app.services import decision_chain

router = APIRouter()


@router.post("")
def create_decision(
    body: DecisionRunRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = decision_chain.run(
            str(user.id),
            codes=normalize_a_share_codes(body.codes),
            as_of=body.asOf,
        )
    except decision_chain.DecisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)


@router.get("")
def decision_history(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict:
    return success(
        {"items": decision_chain.list_runs(str(user.id), limit=limit)}
    )


@router.get("/{run_id}")
def decision_detail(
    run_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = decision_chain.get(str(user.id), run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return success(result)
