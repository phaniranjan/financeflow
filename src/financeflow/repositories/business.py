import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from financeflow.models.business import Business


class BusinessRepository:
    """Repository handling persistence operations for Business entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, business: Business) -> Business:
        """Add a new business entity to the active session."""
        self._session.add(business)
        return business

    def get_by_id(self, business_id: uuid.UUID) -> Business | None:
        """Find a business by its primary key UUID."""
        return self._session.get(Business, business_id)

    def get_by_tax_id(self, tax_id: str) -> Business | None:
        """Find a business by its unique tax ID."""
        stmt = sa.select(Business).where(Business.tax_id == tax_id)
        return self._session.scalars(stmt).first()

    def list_all(self, limit: int = 100, offset: int = 0) -> list[Business]:
        """List businesses ordered by creation date descending with pagination."""
        stmt = sa.select(Business).order_by(Business.created_at.desc()).limit(limit).offset(offset)
        return list(self._session.scalars(stmt).all())
