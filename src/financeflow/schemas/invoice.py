import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InvoiceCreate(BaseModel):
    """Schema for validating invoice creation requests."""

    business_id: uuid.UUID
    invoice_number: str = Field(..., min_length=1, max_length=128)
    debtor_name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, max_digits=19)
    currency: str = Field("USD", min_length=3, max_length=3)
    issue_date: date
    due_date: date

    @field_validator("invoice_number", "debtor_name")
    @classmethod
    def strip_and_validate_non_empty(cls, v: str) -> str:
        """Strip whitespace and reject blank strings."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only")
        return stripped

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        """Normalize currency code to uppercase 3-letter ISO."""
        return v.strip().upper()

    @model_validator(mode="after")
    def validate_dates_sequence(self) -> "InvoiceCreate":
        """Verify due date is greater than or equal to issue date."""
        if self.due_date < self.issue_date:
            raise ValueError("due_date cannot precede issue_date")
        return self


class InvoiceResponse(BaseModel):
    """Schema for serializing invoice representations to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    invoice_number: str
    debtor_name: str
    amount: Decimal
    currency: str
    issue_date: date
    due_date: date
    status: str
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    """Schema for paginated invoice list responses."""

    items: list[InvoiceResponse]
    total: int
    limit: int
    offset: int
