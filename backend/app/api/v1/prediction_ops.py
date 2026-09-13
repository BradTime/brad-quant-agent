from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.core.response import success
from app.models.user import User
from app.schemas.prediction_ops import PredictionOpsEnqueueRequest
from app.services import prediction_ops

router = APIRouter()


@router.get("")
def operations_dashboard(
    _: User = Depends(require_admin),
) -> dict:
    return success(prediction_ops.dashboard())


@router.post("/jobs")
def enqueue_job(
    body: PredictionOpsEnqueueRequest,
    admin: User = Depends(require_admin),
) -> dict:
    try:
        result = prediction_ops.enqueue(
            job_type=body.jobType,
            scheduled_for=body.scheduledFor,
            codes=body.codes,
            provider=body.provider,
            requested_by_user_id=str(admin.id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)
