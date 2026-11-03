import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from financeflow.api.dependencies.auth import (
    AuthenticatedTenant,
    get_current_tenant,
)
from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateInvoiceNumberError,
    InvalidInvoiceAmountError,
    InvalidInvoiceDateError,
)
from financeflow.schemas.invoice import InvoiceCreate, InvoiceListResponse, InvoiceResponse
from financeflow.services.invoice import InvoiceService, get_invoice_service

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.post(
    "",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an invoice for financing",
)
def create_invoice(
    payload: InvoiceCreate,
    service: InvoiceService = Depends(get_invoice_service),
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
) -> InvoiceResponse:
    """Register a new invoice under the authenticated business tenant."""
    if payload.business_id != tenant.business_id and not tenant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot create invoice for a different business tenant",
        )
    try:
        invoice = service.create_invoice(
            business_id=payload.business_id,
            invoice_number=payload.invoice_number,
            debtor_name=payload.debtor_name,
            amount=payload.amount,
            currency=payload.currency,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
        )
        return InvoiceResponse.model_validate(invoice)
    except BusinessNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except BusinessInactiveError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except DuplicateInvoiceNumberError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except (InvalidInvoiceAmountError, InvalidInvoiceDateError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an invoice by ID",
)
def get_invoice(
    invoice_id: uuid.UUID,
    service: InvoiceService = Depends(get_invoice_service),
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
) -> InvoiceResponse:
    """Retrieve details for a specific invoice."""
    invoice = service.get_invoice(invoice_id)
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found",
        )
    if invoice.business_id != tenant.business_id and not tenant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Invoice does not belong to the authenticated business tenant",
        )
    return InvoiceResponse.model_validate(invoice)


@router.get(
    "",
    response_model=InvoiceListResponse,
    status_code=status.HTTP_200_OK,
    summary="List invoices for a business",
)
def list_invoices(
    business_id: uuid.UUID | None = Query(
        None, description="Business ID owning the invoices (defaults to authenticated tenant)"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Records to skip"),
    service: InvoiceService = Depends(get_invoice_service),
    tenant: AuthenticatedTenant = Depends(get_current_tenant),
) -> InvoiceListResponse:
    """List paginated invoices for the authenticated business tenant."""
    effective_business_id = business_id or tenant.business_id
    if effective_business_id != tenant.business_id and not tenant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot query invoices for a different business tenant",
        )
    try:
        invoices = service.list_invoices_by_business(
            business_id=effective_business_id,
            limit=limit,
            offset=offset,
        )
        items = [InvoiceResponse.model_validate(inv) for inv in invoices]
        return InvoiceListResponse(
            items=items,
            total=len(items),
            limit=limit,
            offset=offset,
        )
    except BusinessNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
