from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, require_admin
from app.core.response import success
from app.models.user import User
from app.providers.symbols import normalize_a_share_code
from app.schemas.broker import (
    BrokerBindingRequest,
    FilingProfileRequest,
    RehearsalOrderRequest,
)
from app.services import broker_gateway

router = APIRouter()


@router.post("/filings")
def register_filing(
    body: FilingProfileRequest,
    admin: User = Depends(require_admin),
) -> dict:
    try:
        result = broker_gateway.register_filing(
            user_id=body.userId,
            reviewed_by_user_id=str(admin.id),
            filing_reference=body.filingReference,
            evidence_document_sha256=body.evidenceDocumentSha256,
            professional_eligibility_confirmed=(
                body.professionalEligibilityConfirmed
            ),
            broker_simulation_permission_confirmed=(
                body.brokerSimulationPermissionConfirmed
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)


@router.post("/bindings")
def bind_simulation(
    body: BrokerBindingRequest,
    _: User = Depends(require_admin),
) -> dict:
    try:
        result = broker_gateway.bind_simulation(
            user_id=body.userId,
            filing_profile_id=body.filingProfileId,
            account_id=body.accountId,
            strategy_id=body.strategyId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)


@router.get("/binding")
def my_binding(user: User = Depends(get_current_user)) -> dict:
    return success(broker_gateway.binding_for_user(str(user.id)))


@router.get("/orders")
def my_orders(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict:
    return success(
        {
            "items": broker_gateway.list_orders(
                str(user.id), limit=limit
            )
        }
    )


@router.post("/rehearsal-orders")
def rehearsal_order(
    body: RehearsalOrderRequest,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        result = broker_gateway.enqueue_rehearsal_order(
            user=user,
            binding_id=body.bindingId,
            idempotency_key=body.idempotencyKey,
            code=normalize_a_share_code(body.code),
            side=body.side,
            qty=body.qty,
            limit_price=body.limitPrice,
            step_up_token=body.stepUpToken,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return success(result)
