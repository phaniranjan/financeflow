import abc
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class DisbursementStatus(StrEnum):
    """Lifecycle status of an external disbursement transfer."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class DisbursementRequest(BaseModel):
    """Request payload for initiating an external disbursement transfer."""

    application_id: uuid.UUID
    amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=19)
    currency: str = Field("USD", min_length=3, max_length=3)
    recipient_account: str = Field(..., min_length=1, max_length=128)
    idempotency_key: str = Field(..., min_length=1, max_length=128)

    @field_validator("amount", mode="before")
    @classmethod
    def reject_float_amount(cls, v: object) -> object:
        """Reject float types to preserve financial precision."""
        if isinstance(v, float):
            raise ValueError(
                "Floating-point values are rejected to avoid precision loss. "
                "Pass monetary amounts as strings (e.g. '31040.00') or Decimals."
            )
        return v


class DisbursementResult(BaseModel):
    """Result returned by a disbursement provider."""

    status: DisbursementStatus
    amount: Decimal
    provider_transaction_id: str | None = None
    error_message: str | None = None
    disbursed_at: datetime | None = None


class DisbursementProvider(abc.ABC):
    """Abstract protocol for payment rails and disbursement execution."""

    @abc.abstractmethod
    def disburse(self, request: DisbursementRequest) -> DisbursementResult:
        """Execute or simulate a disbursement transfer to the recipient account."""
        ...
