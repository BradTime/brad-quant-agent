from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.core.response import success
from app.models.user import User
from app.schemas.room import (
    ChangeModeRequest,
    DecisionOverrideRequest,
    KillSwitchRequest,
    ReleaseKillSwitchRequest,
    StepUpRequest,
    TotpConfirmRequest,
    TotpEnrollRequest,
    TotpResetRequest,
)
from app.services import decision_notifications, decision_room, step_up

router = APIRouter()


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
def room_state(user: User = Depends(get_current_user)) -> dict:
    return success(
        {
            **decision_room.state(str(user.id)),
            "totp": step_up.status(str(user.id)),
        }
    )


@router.post("/totp/enroll")
def enroll_totp(
    body: TotpEnrollRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(step_up.enroll(str(user.id), body.password))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/totp/confirm")
def confirm_totp(
    body: TotpConfirmRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(step_up.confirm(str(user.id), body.code))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/step-up")
def create_step_up(
    body: StepUpRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            step_up.create_grant(
                str(user.id),
                password=body.password,
                code=body.code,
                recovery_code=body.recoveryCode,
                purpose=body.purpose,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/totp/reset")
def reset_totp(
    body: TotpResetRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            step_up.reset_factor(user, token=body.stepUpToken)
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/mode")
def change_mode(
    body: ChangeModeRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            decision_room.change_mode(
                user,
                mode=body.mode,
                reason=body.reason,
                step_up_token=body.stepUpToken,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/kill-switch/activate")
def activate_kill_switch(
    body: KillSwitchRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            decision_room.activate_kill_switch(
                str(user.id), reason=body.reason
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/kill-switch/release")
def release_kill_switch(
    body: ReleaseKillSwitchRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            decision_room.release_kill_switch(
                user,
                reason=body.reason,
                step_up_token=body.stepUpToken,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/decisions/{run_id}/override")
def override_decision(
    run_id: str,
    body: DecisionOverrideRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return success(
            decision_room.override(
                user,
                run_id=run_id,
                action=body.action,
                reason=body.reason,
                weights=body.weights,
                step_up_token=body.stepUpToken,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/notifications")
def notifications(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict:
    return success(
        {
            "items": decision_notifications.list_for_user(
                str(user.id), limit=limit
            )
        }
    )
