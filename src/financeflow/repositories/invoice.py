import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from financeflow.models.invoice import Invoice


class InvoiceRepository:
    """Repository handling persistence operations for Invoice entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, invoice: Invoice) -> Invoice:
        """Add a new invoice entity to the active session."""
        self._session.add(invoice)
        return invoice

    def get_by_id(self, invoice_id: uuid.UUID) -> Invoice | None:
        """Find an invoice by its primary key UUID."""
        return self._session.get(Invoice, invoice_id)

    def get_by_number(self, business_id: uuid.UUID, invoice_number: str) -> Invoice | None:
        """Find an invoice by business_id and unique invoice_number."""
        stmt = sa.select(Invoice).where(
            Invoice.business_id == business_id,
            Invoice.invoice_number == invoice_number,
        )
        return self._session.scalars(stmt).first()

    def list_by_business(
        self,
        business_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Invoice]:
        """List invoices for a specific business ordered by creation date descending."""
        stmt = (
            sa.select(Invoice)
            .where(Invoice.business_id == business_id)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(stmt).all())

    def delete(self, invoice: Invoice) -> None:
        """Delete an invoice entity from the active session."""
        self._session.delete(invoice)
