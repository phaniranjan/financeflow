import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from financeflow.db.base import Base

if TYPE_CHECKING:
    from financeflow.models.audit import FinancingAuditLog
    from financeflow.models.business import Business
    from financeflow.models.disbursement import Disbursement
    from financeflow.models.invoice import Invoice
    from financeflow.models.settlement import Settlement


class FinancingStatus(StrEnum):
    """Lifecycle status of a financing application."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    PARTIALLY_SETTLED = "PARTIALLY_SETTLED"
    SETTLED = "SETTLED"


class FinancingApplication(Base):
    """Financing application entity requesting working capital against an invoice."""

    __tablename__ = "financing_applications"

    __table_args__ = (
        CheckConstraint(
            "requested_amount > 0",
            name="ck_financing_requested_amount_positive",
        ),
        CheckConstraint(
            "approved_amount IS NULL OR approved_amount >= 0",
            name="ck_financing_approved_amount_non_negative",
        ),
        CheckConstraint(
            "advance_rate > 0 AND advance_rate <= 1.0",
            name="ck_financing_advance_rate_bounds",
        ),
        CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1.0",
            name="ck_financing_fee_rate_bounds",
        ),
        Index(
            "uq_financing_active_invoice",
            "invoice_id",
            unique=True,
            postgresql_where=text(
                "status IN ('SUBMITTED', 'APPROVED', 'DISBURSED', 'PARTIALLY_SETTLED')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requested_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=False,
    )
    approved_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=True,
    )
    advance_rate: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        default=Decimal("0.8000"),
        nullable=False,
    )
    fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        default=Decimal("0.0300"),
        nullable=False,
    )
    fee_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=True,
    )
    net_disbursement_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=FinancingStatus.SUBMITTED.value,
        nullable=False,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    business: Mapped["Business"] = relationship(
        back_populates="financing_applications",
    )
    invoice: Mapped["Invoice"] = relationship(
        back_populates="financing_applications",
    )
    disbursement: Mapped["Disbursement | None"] = relationship(
        back_populates="financing_application",
        uselist=False,
    )
    settlements: Mapped[list["Settlement"]] = relationship(
        back_populates="financing_application",
    )

    @property
    def settlement(self) -> "Settlement | None":
        """Return the latest settlement record for backward compatibility."""
        return self.settlements[-1] if self.settlements else None

    audit_logs: Mapped[list["FinancingAuditLog"]] = relationship(
        back_populates="financing_application",
    )
