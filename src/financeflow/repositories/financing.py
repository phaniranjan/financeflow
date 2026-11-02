import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from financeflow.models.financing import FinancingApplication, FinancingStatus


class FinancingRepository:
    """Repository handling persistence operations for FinancingApplication entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, application: FinancingApplication) -> FinancingApplication:
        """Add a new financing application to the session and flush."""
        self.session.add(application)
        self.session.flush()
        return application

    def get_by_id(self, application_id: uuid.UUID) -> FinancingApplication | None:
        """Retrieve a financing application by its primary key UUID."""
        return self.session.get(FinancingApplication, application_id)

    def list_by_business(
        self,
        business_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FinancingApplication]:
        """List financing applications for a business, sorted newest first."""
        stmt = (
            select(FinancingApplication)
            .where(FinancingApplication.business_id == business_id)
            .order_by(FinancingApplication.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all())

    def get_active_by_invoice(
        self,
        invoice_id: uuid.UUID,
    ) -> FinancingApplication | None:
        """Find an existing active financing application for an invoice."""
        active_statuses = [
            FinancingStatus.SUBMITTED.value,
            FinancingStatus.APPROVED.value,
            FinancingStatus.DISBURSED.value,
        ]
        stmt = (
            select(FinancingApplication)
            .where(
                FinancingApplication.invoice_id == invoice_id,
                FinancingApplication.status.in_(active_statuses),
            )
            .limit(1)
        )
        return self.session.scalars(stmt).first()
