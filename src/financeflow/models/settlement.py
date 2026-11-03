import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from financeflow.db.base import Base

if TYPE_CHECKING:
    from financeflow.models.financing import FinancingApplication
    from financeflow.models.invoice import Invoice


class SettlementStatus(StrEnum):
    """Lifecycle status of a financing settlement."""

    COMPLETED = "COMPLETED"
    SHORTFALL = "SHORTFALL"


class Settlement(Base):
    """Settlement entity tracking debtor invoice collection and client reserve release."""

    __tablename__ = "settlements"

    __table_args__ = (
        CheckConstraint(
            "repayment_amount > 0",
            name="ck_settlement_repayment_positive",
        ),
        CheckConstraint(
            "principal_repaid >= 0",
            name="ck_settlement_principal_non_negative",
        ),
        CheckConstraint(
            "reserve_amount >= 0",
            name="ck_settlement_reserve_non_negative",
        ),
        CheckConstraint(
            "settlement_fee >= 0",
            name="ck_settlement_fee_non_negative",
        ),
        CheckConstraint(
            "net_reserve_refunded >= 0",
            name="ck_settlement_refund_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    financing_application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financing_applications.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repayment_amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 2),
        nullable=False,
    )
    principal_repaid: Mapped[Decimal] = mapped_column(
        Numeric(19, 2),
        nullable=False,
    )
    reserve_amount: Mapped[Decimal] = mapped_column(
        Numeric(19, 2),
        nullable=False,
    )
    settlement_fee: Mapped[Decimal] = mapped_column(
        Numeric(19, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    net_reserve_refunded: Mapped[Decimal] = mapped_column(
        Numeric(19, 2),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SettlementStatus.COMPLETED.value,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    settled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
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

    # Relationships
    financing_application: Mapped["FinancingApplication"] = relationship(
        "FinancingApplication",
        back_populates="settlement",
    )
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
    )
