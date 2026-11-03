import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from financeflow.core.exceptions import (
    DuplicateSettlementError,
    FinancingApplicationNotFoundError,
    InvalidSettlementAmountError,
    InvalidSettlementStateError,
)
from financeflow.schemas.settlement import (
    SettlementRequest,
    SettlementResponse,
)
from financeflow.services.settlement import (
    SettlementService,
    get_settlement_service,
)

router = APIRouter(tags=["Settlements"])


@router.post(
    "/financing/{application_id}/settle",
    response_model=SettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute debtor repayment settlement and reserve release",
)
def execute_settlement(
    application_id: uuid.UUID,
    payload: SettlementRequest,
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Execute settlement for a financing application, clearing receivables and reserve."""
    try:
        settlement = service.execute_settlement(
            application_id=application_id,
            repayment_amount=payload.repayment_amount,
            settlement_fee=payload.settlement_fee,
            idempotency_key=payload.idempotency_key,
            correlation_id=payload.correlation_id,
        )
        return SettlementResponse.model_validate(settlement)
    except FinancingApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DuplicateSettlementError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvalidSettlementStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except InvalidSettlementAmountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/financing/{application_id}/settlement",
    response_model=SettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve settlement record for a financing application",
)
def get_settlement_by_application(
    application_id: uuid.UUID,
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Retrieve settlement associated with a specific financing application."""
    settlement = service.get_settlement_by_application(application_id)
    if settlement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Settlement for application {application_id} not found",
        )
    return SettlementResponse.model_validate(settlement)


@router.get(
    "/settlements/{settlement_id}",
    response_model=SettlementResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve settlement record by ID",
)
def get_settlement(
    settlement_id: uuid.UUID,
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Retrieve a settlement record by its UUID."""
    settlement = service.get_settlement(settlement_id)
    if settlement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Settlement {settlement_id} not found",
        )
    return SettlementResponse.model_validate(settlement)
