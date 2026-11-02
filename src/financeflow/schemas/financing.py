import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FinancingApplicationCreate(BaseModel):
    """Schema for submitting a financing application against an invoice."""

    business_id: uuid.UUID
    invoice_id: uuid.UUID
    requested_amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=19)
    advance_rate: Decimal = Field(
        Decimal("0.8000"),
        gt=Decimal("0.0000"),
        le=Decimal("1.0000"),
        decimal_places=4,
    )
    fee_rate: Decimal = Field(
        Decimal("0.0300"),
        ge=Decimal("0.0000"),
        le=Decimal("1.0000"),
        decimal_places=4,
    )

    @field_validator("requested_amount", "advance_rate", "fee_rate", mode="before")
    @classmethod
    def reject_float_values(cls, v: object) -> object:
        """Reject float types at API boundary to preserve exact decimal precision."""
        if isinstance(v, float):
            raise ValueError(
                "Floating-point values are rejected to avoid precision loss. "
                "Pass monetary amounts and rates as strings (e.g. '1500.50', '0.8000') or Decimals."
            )
        return v


class FinancingDecisionRequest(BaseModel):
    """Schema for approving or rejecting a financing application with optional notes."""

    reason: str | None = Field(None, max_length=512)


class FinancingApplicationResponse(BaseModel):
    """Schema for serializing financing application representations."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    invoice_id: uuid.UUID
    requested_amount: Decimal
    approved_amount: Decimal | None
    advance_rate: Decimal
    fee_rate: Decimal
    fee_amount: Decimal | None
    net_disbursement_amount: Decimal | None
    status: str
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class FinancingApplicationListResponse(BaseModel):
    """Schema for paginated financing application results."""

    total: int
    items: list[FinancingApplicationResponse]
    limit: int
    offset: int
