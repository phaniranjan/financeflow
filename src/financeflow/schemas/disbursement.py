import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DisbursementCreateRequest(BaseModel):
    """Schema for requesting fund disbursement against an approved financing application."""

    recipient_account: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="Destination bank account or routing identifier",
        examples=["ACC-883920194"],
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Unique client-provided idempotency key preventing duplicate payouts",
        examples=["idemp-disb-883920194"],
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional correlation identifier for distributed tracing and audit logging",
    )


class DisbursementResponse(BaseModel):
    """Schema for serializing disbursement execution details."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    financing_application_id: uuid.UUID
    idempotency_key: str
    amount: Decimal
    recipient_account: str
    status: str
    provider_transaction_id: str | None
    disbursed_at: datetime | None
    created_at: datetime
    updated_at: datetime
