import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettlementRequest(BaseModel):
    """Schema for executing debtor repayment, receivable extinguishment, and reserve refund."""

    repayment_amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        max_digits=19,
        description="Total repayment funds collected from debtor",
        examples=["50000.00"],
    )
    settlement_fee: Decimal = Field(
        default=Decimal("0.00"),
        ge=Decimal("0.00"),
        decimal_places=2,
        max_digits=19,
        description="Optional settlement processing fee deducted from reserve",
        examples=["100.00"],
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Unique client-provided idempotency key",
        examples=["idemp-settle-001"],
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional correlation identifier for distributed tracing and audit logging",
    )

    @field_validator("repayment_amount", "settlement_fee", mode="before")
    @classmethod
    def reject_float_amounts(cls, v: object) -> object:
        """Reject float types at API boundaries to protect monetary precision."""
        if isinstance(v, float):
            raise ValueError(
                "Floating-point values are rejected to avoid precision loss. "
                "Pass monetary amounts as strings (e.g. '50000.00') or Decimals."
            )
        return v


class SettlementResponse(BaseModel):
    """Schema for serializing settlement execution representations."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    financing_application_id: uuid.UUID
    invoice_id: uuid.UUID
    repayment_amount: Decimal
    principal_repaid: Decimal
    reserve_amount: Decimal
    settlement_fee: Decimal
    net_reserve_refunded: Decimal
    status: str
    idempotency_key: str
    settled_at: datetime
    created_at: datetime
    updated_at: datetime
