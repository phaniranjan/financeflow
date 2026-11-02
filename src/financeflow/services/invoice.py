import uuid
from datetime import date
from decimal import Decimal

from fastapi import Depends
from sqlalchemy.orm import Session

from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateInvoiceNumberError,
    InvalidInvoiceAmountError,
    InvalidInvoiceDateError,
)
from financeflow.db.session import get_db
from financeflow.models.invoice import Invoice
from financeflow.repositories.business import BusinessRepository
from financeflow.repositories.invoice import InvoiceRepository


class InvoiceService:
    """Domain service managing the lifecycle and business rules of invoices."""

    def __init__(
        self,
        session: Session,
        invoice_repo: InvoiceRepository,
        business_repo: BusinessRepository,
    ) -> None:
        self._session = session
        self._invoice_repo = invoice_repo
        self._business_repo = business_repo

    def create_invoice(
        self,
        business_id: uuid.UUID,
        invoice_number: str,
        debtor_name: str,
        amount: Decimal,
        currency: str,
        issue_date: date,
        due_date: date,
    ) -> Invoice:
        """Validate domain invariants, persist invoice, and commit the transaction boundary."""
        # 1. Verify business existence
        business = self._business_repo.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError(f"Business {business_id} not found")

        # 2. Verify business is ACTIVE
        if business.status != "ACTIVE":
            raise BusinessInactiveError(f"Business {business_id} is not active")

        # 3. Verify positive financial amount
        if amount <= Decimal("0.00"):
            raise InvalidInvoiceAmountError("Invoice amount must be positive")

        # 4. Verify sequence of dates
        if due_date < issue_date:
            raise InvalidInvoiceDateError("Due date cannot precede invoice issue date")

        # 5. Check duplicate invoice number for business
        existing = self._invoice_repo.get_by_number(business_id, invoice_number)
        if existing is not None:
            raise DuplicateInvoiceNumberError(
                f"Invoice number '{invoice_number}' already exists for this business"
            )

        # 6. Instantiate and persist within the service-owned transaction boundary
        invoice = Invoice(
            business_id=business_id,
            invoice_number=invoice_number,
            debtor_name=debtor_name,
            amount=amount,
            currency=currency,
            issue_date=issue_date,
            due_date=due_date,
            status="SUBMITTED",
        )
        self._invoice_repo.create(invoice)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        return invoice

    def get_invoice(self, invoice_id: uuid.UUID) -> Invoice | None:
        """Retrieve an invoice by primary key UUID."""
        return self._invoice_repo.get_by_id(invoice_id)

    def list_invoices_by_business(
        self,
        business_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Invoice]:
        """List invoices for a business, verifying business existence first."""
        business = self._business_repo.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError(f"Business {business_id} not found")

        return self._invoice_repo.list_by_business(
            business_id=business_id,
            limit=limit,
            offset=offset,
        )


def get_invoice_service(
    session: Session = Depends(get_db),
) -> InvoiceService:
    """FastAPI dependency provider injecting repositories and session into InvoiceService."""
    invoice_repo = InvoiceRepository(session)
    business_repo = BusinessRepository(session)
    return InvoiceService(
        session=session,
        invoice_repo=invoice_repo,
        business_repo=business_repo,
    )
