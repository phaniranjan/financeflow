import uuid
from datetime import datetime
from decimal import Decimal
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


class Disbursement(Base):
    """Disbursement entity tracking funds transfer execution for a financing application."""

    __tablename__ = "disbursements"

    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_disbursements_amount_positive",
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
        unique=True,
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=False,
    )
    recipient_account: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    disbursed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    financing_application: Mapped["FinancingApplication"] = relationship(
        back_populates="disbursement",
    )
