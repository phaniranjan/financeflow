import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from financeflow.models.audit import FinancingAuditLog


class AuditRepository:
    """Repository handling persistence and queries for FinancingAuditLog records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, log: FinancingAuditLog) -> FinancingAuditLog:
        """Add a new audit log record to the session and flush."""
        self.session.add(log)
        self.session.flush()
        return log

    def list_by_application(self, application_id: uuid.UUID) -> list[FinancingAuditLog]:
        """List audit events for a financing application, ordered chronologically."""
        stmt = (
            select(FinancingAuditLog)
            .where(FinancingAuditLog.application_id == application_id)
            .order_by(FinancingAuditLog.created_at)
        )
        return list(self.session.scalars(stmt).all())
