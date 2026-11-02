import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateFinancingError,
    FinancingApplicationNotFoundError,
    InvalidFinancingAmountError,
    InvalidFinancingStateTransitionError,
    InvalidFinancingTermsError,
    InvoiceNotEligibleError,
    InvoiceNotFoundError,
)
from financeflow.schemas.financing import (
    FinancingApplicationCreate,
    FinancingApplicationListResponse,
    FinancingApplicationResponse,
    FinancingDecisionRequest,
)
from financeflow.services.financing import FinancingService, get_financing_service

router = APIRouter(prefix="/financing", tags=["Financing"])


@router.post(
    "",
    response_model=FinancingApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a financing application for an invoice",
)
def create_financing_application(
    payload: FinancingApplicationCreate,
    service: FinancingService = Depends(get_financing_service),
) -> FinancingApplicationResponse:
    """Submit a financing application against an existing submitted invoice."""
    try:
        application = service.create_application(
            business_id=payload.business_id,
            invoice_id=payload.invoice_id,
            requested_amount=payload.requested_amount,
            advance_rate=payload.advance_rate,
            fee_rate=payload.fee_rate,
        )
        return FinancingApplicationResponse.model_validate(application)
    except (BusinessNotFoundError, InvoiceNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DuplicateFinancingError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        BusinessInactiveError,
        InvoiceNotEligibleError,
        InvalidFinancingAmountError,
        InvalidFinancingTermsError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{application_id}",
    response_model=FinancingApplicationResponse,
    summary="Get financing application by ID",
)
def get_financing_application(
    application_id: uuid.UUID,
    service: FinancingService = Depends(get_financing_service),
) -> FinancingApplicationResponse:
    """Retrieve detailed state of a financing application."""
    application = service.get_application(application_id)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Financing application {application_id} not found",
        )
    return FinancingApplicationResponse.model_validate(application)


@router.get(
    "",
    response_model=FinancingApplicationListResponse,
    summary="List financing applications for a business",
)
def list_financing_applications(
    business_id: uuid.UUID = Query(..., description="ID of the business"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    service: FinancingService = Depends(get_financing_service),
) -> FinancingApplicationListResponse:
    """Retrieve paginated financing applications for a business."""
    try:
        applications = service.list_applications_by_business(
            business_id=business_id,
            limit=limit,
            offset=offset,
        )
    except BusinessNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return FinancingApplicationListResponse(
        total=len(applications),
        items=[FinancingApplicationResponse.model_validate(a) for a in applications],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{application_id}/approve",
    response_model=FinancingApplicationResponse,
    summary="Approve a submitted financing application",
)
def approve_financing_application(
    application_id: uuid.UUID,
    service: FinancingService = Depends(get_financing_service),
) -> FinancingApplicationResponse:
    """Approve financing application and transition invoice status."""
    try:
        application = service.approve_application(application_id)
        return FinancingApplicationResponse.model_validate(application)
    except FinancingApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidFinancingStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/{application_id}/reject",
    response_model=FinancingApplicationResponse,
    summary="Reject a submitted financing application",
)
def reject_financing_application(
    application_id: uuid.UUID,
    decision: FinancingDecisionRequest | None = None,
    service: FinancingService = Depends(get_financing_service),
) -> FinancingApplicationResponse:
    """Reject financing application with optional reason."""
    reason = decision.reason if decision else None
    try:
        application = service.reject_application(application_id, reason=reason)
        return FinancingApplicationResponse.model_validate(application)
    except FinancingApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidFinancingStateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
