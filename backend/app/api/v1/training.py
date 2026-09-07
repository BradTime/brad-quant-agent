"""Consent-bound training feedback and admin review endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_admin
from app.core.response import success
from app.models.user import User
from app.schemas.training import CandidateReview, ConsentUpdate, DatasetBuildRequest, FeedbackUpsert
from app.services import training_data

router = APIRouter()


def _bad_request(exc: training_data.TrainingDataError) -> HTTPException:
    message = str(exc)
    status = 404 if "不存在" in message else 400
    return HTTPException(status_code=status, detail=message)


@router.get("/data")
def export_my_training_data(user: User = Depends(get_current_user)) -> dict:
    return success(training_data.export_user_data(str(user.id)))


@router.delete("/data")
def erase_my_training_data(user: User = Depends(get_current_user)) -> dict:
    return success(training_data.erase_user_data(str(user.id)))


@router.get("/consent/{session_id}")
def consent_status(
    session_id: str, user: User = Depends(get_current_user)
) -> dict:
    try:
        result = training_data.get_consent(str(user.id), session_id)
    except training_data.TrainingDataError as exc:
        raise _bad_request(exc) from exc
    return success(result)


@router.put("/consent/{session_id}")
def update_consent(
    session_id: str,
    body: ConsentUpdate,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = training_data.set_consent(str(user.id), session_id, body.enabled)
    except training_data.TrainingDataError as exc:
        raise _bad_request(exc) from exc
    return success(result)


@router.put("/feedback/{assistant_message_id}")
def feedback(
    assistant_message_id: str,
    body: FeedbackUpsert,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = training_data.submit_feedback(
            str(user.id),
            assistant_message_id,
            body.rating,
            body.issueLabels,
            body.comment,
        )
    except training_data.TrainingDataError as exc:
        raise _bad_request(exc) from exc
    return success(result)


@router.get("/admin/candidates")
def candidates(
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None, alias="taskType"),
    rating: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    _admin: User = Depends(require_admin),
) -> dict:
    return success(
        training_data.list_candidates(
            status,
            limit,
            task_type=task_type,
            rating=rating,
        )
    )


@router.put("/admin/candidates/{candidate_id}")
def review(
    candidate_id: str,
    body: CandidateReview,
    admin: User = Depends(require_admin),
) -> dict:
    try:
        result = training_data.review_candidate(
            candidate_id,
            str(admin.id),
            status=body.status,
            task_type=body.taskType,
            ideal_answer=body.idealAnswer,
            quality_labels=body.qualityLabels,
            review_note=body.reviewNote,
        )
    except training_data.TrainingDataError as exc:
        raise _bad_request(exc) from exc
    return success(result)


@router.post("/admin/datasets")
def build_dataset(
    body: DatasetBuildRequest,
    admin: User = Depends(require_admin),
) -> dict:
    from app.services import training_dataset

    try:
        result = training_dataset.build_dataset(body.version, str(admin.id))
    except training_data.TrainingDataError as exc:
        raise _bad_request(exc) from exc
    return success(result)


@router.get("/admin/readiness")
def readiness(_admin: User = Depends(require_admin)) -> dict:
    from app.services import training_dataset

    return success(training_dataset.readiness())
