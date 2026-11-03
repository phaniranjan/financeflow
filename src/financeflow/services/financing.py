import uuid
from decimal import Decimal

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
from financeflow.core.precision import quantize_currency
from financeflow.db.session import get_db
from financeflow.models.business import BusinessStatus
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import InvoiceStatus
from financeflow.repositories.business import BusinessRepository
from financeflow.repositories.financing import FinancingRepository
from financeflow.repositories.invoice import InvoiceRepository


class FinancingService:
    """Domain service managing lifecycle, eligibility, and decisions of financing applications."""

    def __init__(
        self,
        session: Session,
        financing_repo: FinancingRepository,
        invoice_repo: InvoiceRepository,
        business_repo: BusinessRepository,
    ) -> None:
        self._session = session
        self._financing_repo = financing_repo
        self._invoice_repo = invoice_repo
        self._business_repo = business_repo

    def create_application(
        self,
        business_id: uuid.UUID,
        invoice_id: uuid.UUID,
        requested_amount: Decimal,
        advance_rate: Decimal = Decimal("0.8000"),
        fee_rate: Decimal = Decimal("0.0300"),
    ) -> FinancingApplication:
        """Validate eligibility invariants and submit a financing application."""
        # 1. Verify business existence
        business = self._business_repo.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError(f"Business {business_id} not found")

        # 2. Verify business is ACTIVE
        if business.status != BusinessStatus.ACTIVE:
            raise BusinessInactiveError(f"Business {business_id} is not active")

        # 3. Verify invoice existence
        invoice = self._invoice_repo.get_by_id(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"Invoice {invoice_id} not found")

        # 4. Verify invoice ownership
        if invoice.business_id != business_id:
            raise InvoiceNotEligibleError("Invoice does not belong to the specified business")

        # 5. Verify invoice status is SUBMITTED
        if invoice.status != InvoiceStatus.SUBMITTED:
            raise InvoiceNotEligibleError("Only SUBMITTED invoices are eligible for financing")

        # 6. Verify requested amount is positive and does not exceed invoice total
        if requested_amount <= Decimal("0.00"):
            raise InvalidFinancingAmountError("Requested amount must be positive")
        if requested_amount > invoice.amount:
            raise InvalidFinancingAmountError(
                f"Requested amount ({requested_amount}) cannot exceed invoice ({invoice.amount})"
            )

        # 7. Verify terms (advance rate and fee rate) bounds
        if advance_rate <= Decimal("0.0000") or advance_rate > Decimal("1.0000"):
            raise InvalidFinancingTermsError("Advance rate must be between 0.0001 and 1.0000")
        if fee_rate < Decimal("0.0000") or fee_rate > Decimal("1.0000"):
            raise InvalidFinancingTermsError("Fee rate must be between 0.0000 and 1.0000")

        # 8. Check duplicate active financing application
        existing_active = self._financing_repo.get_active_by_invoice(invoice_id)
        if existing_active is not None:
            raise DuplicateFinancingError(
                f"Invoice {invoice_id} already has an active financing application"
            )

        # 9. Instantiate, persist, and commit
        application = FinancingApplication(
            business_id=business_id,
            invoice_id=invoice_id,
            requested_amount=requested_amount,
            advance_rate=advance_rate,
            fee_rate=fee_rate,
            status=FinancingStatus.SUBMITTED.value,
        )
        try:
            self._financing_repo.create(application)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            error_msg = str(exc).lower()
            if "uq_financing_active_invoice" in error_msg or "unique constraint" in error_msg:
                raise DuplicateFinancingError(
                    f"Invoice {invoice_id} already has an active financing application"
                ) from exc
            raise
        except Exception:
            self._session.rollback()
            raise

        return application

    def approve_application(
        self,
        application_id: uuid.UUID,
    ) -> FinancingApplication:
        """Approve application, calculate financial terms, and transition invoice atomically."""
        application = self._financing_repo.get_by_id(application_id, for_update=True)
        if application is None:
            raise FinancingApplicationNotFoundError(f"Application {application_id} not found")

        if application.status != FinancingStatus.SUBMITTED.value:
            raise InvalidFinancingStateTransitionError(
                f"Cannot approve application in {application.status} status"
            )

        # Calculate exact financial amounts
        approved_amount = quantize_currency(application.requested_amount * application.advance_rate)
        fee_amount = quantize_currency(approved_amount * application.fee_rate)
        net_disbursement = quantize_currency(approved_amount - fee_amount)

        application.approved_amount = approved_amount
        application.fee_amount = fee_amount
        application.net_disbursement_amount = net_disbursement
        application.status = FinancingStatus.APPROVED.value

        # Atomically transition invoice status
        invoice = self._invoice_repo.get_by_id(application.invoice_id)
        if invoice is not None:
            invoice.status = InvoiceStatus.APPROVED.value

        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        return application

    def reject_application(
        self,
        application_id: uuid.UUID,
        reason: str | None = None,
    ) -> FinancingApplication:
        """Reject application and record rejection reason."""
        application = self._financing_repo.get_by_id(application_id)
        if application is None:
            raise FinancingApplicationNotFoundError(f"Application {application_id} not found")

        if application.status != FinancingStatus.SUBMITTED.value:
            raise InvalidFinancingStateTransitionError(
                f"Cannot reject application in {application.status} status"
            )

        application.status = FinancingStatus.REJECTED.value
        application.rejection_reason = reason

        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        return application

    def get_application(
        self,
        application_id: uuid.UUID,
    ) -> FinancingApplication | None:
        """Retrieve financing application by ID."""
        return self._financing_repo.get_by_id(application_id)

    def list_applications_by_business(
        self,
        business_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FinancingApplication]:
        """List financing applications for a business with pagination."""
        business = self._business_repo.get_by_id(business_id)
        if business is None:
            raise BusinessNotFoundError(f"Business {business_id} not found")

        return self._financing_repo.list_by_business(
            business_id=business_id,
            limit=limit,
            offset=offset,
        )


def get_financing_service(
    session: Session = Depends(get_db),
) -> FinancingService:
    """FastAPI dependency provider injecting repositories and session into FinancingService."""
    financing_repo = FinancingRepository(session)
    invoice_repo = InvoiceRepository(session)
    business_repo = BusinessRepository(session)
    return FinancingService(
        session=session,
        financing_repo=financing_repo,
        invoice_repo=invoice_repo,
        business_repo=business_repo,
    )
