import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.schemas.disbursement import (
    DisbursementCreateRequest,
    DisbursementResponse,
)
from financeflow.schemas.ledger import (
    LedgerAccountResponse,
    LedgerEntryResponse,
    LedgerTransactionResponse,
    TrialBalanceResponse,
)


class TestDisbursementSchemas:
    """Unit tests for disbursement request and response schemas."""

    @pytest.mark.unit
    def test_disbursement_create_request_valid(self) -> None:
        """Valid disbursement request succeeds."""
        req = DisbursementCreateRequest(
            recipient_account="ACC-123456",
            idempotency_key="idemp-key-123456",
            correlation_id="corr-123",
        )
        assert req.recipient_account == "ACC-123456"
        assert req.idempotency_key == "idemp-key-123456"
        assert req.correlation_id == "corr-123"

    @pytest.mark.unit
    def test_disbursement_create_request_defaults(self) -> None:
        """Correlation ID defaults to None."""
        req = DisbursementCreateRequest(
            recipient_account="ACC-123456",
            idempotency_key="idemp-key-123456",
        )
        assert req.correlation_id is None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("recipient", "idemp"),
        [
            ("123", "idemp-key-123"),  # recipient too short (< 4)
            ("ACC-123456", "short"),  # idempotency_key too short (< 8)
        ],
    )
    def test_disbursement_create_request_validation_errors(
        self, recipient: str, idemp: str
    ) -> None:
        """Fails when string constraints are violated."""
        with pytest.raises(ValidationError):
            DisbursementCreateRequest(
                recipient_account=recipient,
                idempotency_key=idemp,
            )

    @pytest.mark.unit
    def test_disbursement_response_serialization(self) -> None:
        """DisbursementResponse serializes all required attributes."""
        now = datetime.now(UTC)
        disb_id = uuid.uuid4()
        app_id = uuid.uuid4()
        resp = DisbursementResponse(
            id=disb_id,
            financing_application_id=app_id,
            idempotency_key="idemp-key-123456",
            amount=Decimal("38800.00"),
            recipient_account="ACC-123456",
            status="COMPLETED",
            provider_transaction_id="TX-123",
            disbursed_at=now,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == disb_id
        assert resp.amount == Decimal("38800.00")
        assert resp.status == "COMPLETED"


class TestLedgerSchemas:
    """Unit tests for ledger response schemas."""

    @pytest.mark.unit
    def test_ledger_account_response(self) -> None:
        """LedgerAccountResponse serializes correctly."""
        now = datetime.now(UTC)
        acc_id = uuid.uuid4()
        resp = LedgerAccountResponse(
            id=acc_id,
            account_number="1010",
            name="Cash",
            account_type="ASSET",
            balance=Decimal("50000.00"),
            created_at=now,
        )
        assert resp.account_number == "1010"
        assert resp.balance == Decimal("50000.00")

    @pytest.mark.unit
    def test_trial_balance_response(self) -> None:
        """TrialBalanceResponse serializes correctly."""
        resp = TrialBalanceResponse(
            is_balanced=True,
            total_debits=Decimal("1000.00"),
            total_credits=Decimal("1000.00"),
            discrepancy=Decimal("0.00"),
        )
        assert resp.is_balanced is True
        assert resp.discrepancy == Decimal("0.00")

    @pytest.mark.unit
    def test_ledger_transaction_response(self) -> None:
        """LedgerTransactionResponse and LedgerEntryResponse serialize correctly."""
        now = datetime.now(UTC)
        tx_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        acc_id = uuid.uuid4()

        entry = LedgerEntryResponse(
            id=entry_id,
            transaction_id=tx_id,
            account_id=acc_id,
            entry_type="DEBIT",
            amount=Decimal("100.00"),
            created_at=now,
        )
        tx = LedgerTransactionResponse(
            id=tx_id,
            transaction_type="FINANCING_DISBURSEMENT",
            reference_id=uuid.uuid4(),
            description="Test tx",
            created_at=now,
            entries=[entry],
        )
        assert tx.id == tx_id
        assert len(tx.entries) == 1
        assert tx.entries[0].amount == Decimal("100.00")
