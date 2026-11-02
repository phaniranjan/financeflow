import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from financeflow.db.base import Base
from financeflow.models.business import Business


class Invoice(Base):
    """Invoice entity submitted by a business for financing."""

    __tablename__ = "invoices"

    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "invoice_number",
            name="uq_invoices_business_id_invoice_number",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_invoices_amount_positive",
        ),
        CheckConstraint(
            "due_date >= issue_date",
            name="ck_invoices_due_date_after_issue_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_number: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    debtor_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=19, scale=2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        nullable=False,
    )
    issue_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="SUBMITTED",
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

    business: Mapped["Business"] = relationship(
        back_populates="invoices",
    )
