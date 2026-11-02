import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from financeflow.models.disbursement import Disbursement


class DisbursementRepository:
    """Repository handling persistence for Disbursement entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, disbursement: Disbursement) -> Disbursement:
        """Add a new disbursement to the session and flush."""
        self.session.add(disbursement)
        self.session.flush()
        return disbursement

    def get_by_id(self, disbursement_id: uuid.UUID) -> Disbursement | None:
        """Retrieve disbursement by its primary key UUID."""
        return self.session.get(Disbursement, disbursement_id)

    def get_by_application_id(self, application_id: uuid.UUID) -> Disbursement | None:
        """Find disbursement associated with a specific financing application."""
        stmt = (
            select(Disbursement)
            .where(Disbursement.financing_application_id == application_id)
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Disbursement | None:
        """Find disbursement by unique idempotency key."""
        stmt = select(Disbursement).where(Disbursement.idempotency_key == idempotency_key).limit(1)
        return self.session.scalars(stmt).first()
