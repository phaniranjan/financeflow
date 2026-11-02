import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from financeflow.core.exceptions import (
    DisbursementExecutionError,
    DuplicateDisbursementError,
    FinancingApplicationNotFoundError,
    InvalidDisbursementStateError,
)
from financeflow.schemas.disbursement import (
    DisbursementCreateRequest,
    DisbursementResponse,
)
from financeflow.services.disbursement import (
    DisbursementService,
    get_disbursement_service,
)

router = APIRouter(tags=["Disbursements"])


@router.post(
    "/financing/{application_id}/disburse",
    response_model=DisbursementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute disbursement payout for an approved financing application",
)
def execute_disbursement(
    application_id: uuid.UUID,
    payload: DisbursementCreateRequest,
    service: DisbursementService = Depends(get_disbursement_service),
) -> DisbursementResponse:
    """Execute payout to recipient bank account with idempotency and double-entry ledger posting."""
    try:
        disbursement = service.execute_disbursement(
            application_id=application_id,
            recipient_account=payload.recipient_account,
            idempotency_key=payload.idempotency_key,
            correlation_id=payload.correlation_id,
        )
        return DisbursementResponse.model_validate(disbursement)
    except FinancingApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DuplicateDisbursementError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvalidDisbursementStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except DisbursementExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get(
    "/financing/{application_id}/disbursement",
    response_model=DisbursementResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve disbursement record for a financing application",
)
def get_disbursement_by_application(
    application_id: uuid.UUID,
    service: DisbursementService = Depends(get_disbursement_service),
) -> DisbursementResponse:
    """Retrieve the disbursement associated with a specific financing application."""
    disbursement = service.get_disbursement_by_application(application_id)
    if disbursement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disbursement for application {application_id} not found",
        )
    return DisbursementResponse.model_validate(disbursement)


@router.get(
    "/disbursements/{disbursement_id}",
    response_model=DisbursementResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve disbursement record by ID",
)
def get_disbursement(
    disbursement_id: uuid.UUID,
    service: DisbursementService = Depends(get_disbursement_service),
) -> DisbursementResponse:
    """Retrieve a disbursement record by its UUID."""
    disbursement = service.get_disbursement(disbursement_id)
    if disbursement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Disbursement {disbursement_id} not found",
        )
    return DisbursementResponse.model_validate(disbursement)
