import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from financeflow.models.settlement import Settlement


class SettlementRepository:
    """Repository handling persistence and queries for the Settlement entity."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, settlement: Settlement) -> Settlement:
        """Add a new settlement record to the session and flush."""
        self.session.add(settlement)
        self.session.flush()
        return settlement

    def get_by_id(self, settlement_id: uuid.UUID) -> Settlement | None:
        """Find a settlement by its primary key UUID."""
        return self.session.get(Settlement, settlement_id)

    def get_by_application_id(self, application_id: uuid.UUID) -> Settlement | None:
        """Find settlement associated with a specific financing application."""
        stmt = (
            select(Settlement).where(Settlement.financing_application_id == application_id).limit(1)
        )
        return self.session.scalars(stmt).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Settlement | None:
        """Find settlement by unique client idempotency key."""
        stmt = select(Settlement).where(Settlement.idempotency_key == idempotency_key).limit(1)
        return self.session.scalars(stmt).first()
