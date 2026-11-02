import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from financeflow.db.base import Base

if TYPE_CHECKING:
    from financeflow.models.financing import FinancingApplication


class FinancingAuditLog(Base):
    """Immutable audit trail of financing lifecycle transitions and operational events."""

    __tablename__ = "financing_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financing_applications.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    to_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(64),
        default="SYSTEM",
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    financing_application: Mapped["FinancingApplication"] = relationship(
        back_populates="audit_logs",
    )
