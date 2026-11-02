import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LedgerEntryResponse(BaseModel):
    """Schema for individual debit or credit ledger journal entries."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    account_id: uuid.UUID
    entry_type: str
    amount: Decimal
    created_at: datetime


class LedgerTransactionResponse(BaseModel):
    """Schema for multi-legged double-entry financial transactions."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_type: str
    reference_id: uuid.UUID | None
    description: str | None
    created_at: datetime
    entries: list[LedgerEntryResponse] = []


class LedgerAccountResponse(BaseModel):
    """Schema representing an account in the general chart of accounts."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_number: str
    name: str
    account_type: str
    balance: Decimal = Decimal("0.00")
    created_at: datetime


class TrialBalanceResponse(BaseModel):
    """Schema for general ledger trial balance reconciliation audit."""

    is_balanced: bool = Field(..., description="True if total debits equal total credits")
    total_debits: Decimal = Field(..., description="Sum of all debit entries in the ledger")
    total_credits: Decimal = Field(..., description="Sum of all credit entries in the ledger")
    discrepancy: Decimal = Field(..., description="Debit minus credit discrepancy (must be 0.00)")
