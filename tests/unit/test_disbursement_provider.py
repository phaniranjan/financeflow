import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.integrations.disbursement.provider import (
    DisbursementProvider,
    DisbursementRequest,
    DisbursementStatus,
)
from financeflow.integrations.disbursement.simulated import SimulatedDisbursementProvider


class TestDisbursementProviderProtocolAndModels:
    """Unit tests for disbursement request/result data structures and validation."""

    @pytest.mark.unit
    def test_disbursement_request_valid(self) -> None:
        """Verify valid disbursement request creation with Decimal amount."""
        app_id = uuid.uuid4()
        req = DisbursementRequest(
            application_id=app_id,
            amount=Decimal("31040.00"),
            currency="USD",
            recipient_account="ACC-US-987654",
            idempotency_key="idemp-key-001",
        )
        assert req.application_id == app_id
        assert req.amount == Decimal("31040.00")
        assert req.currency == "USD"
        assert req.recipient_account == "ACC-US-987654"
        assert req.idempotency_key == "idemp-key-001"

    @pytest.mark.unit
    def test_disbursement_request_rejects_float_amount(self) -> None:
        """Verify raw JSON float is rejected to prevent precision loss."""
        with pytest.raises(ValidationError, match="Floating-point values are rejected"):
            DisbursementRequest(
                application_id=uuid.uuid4(),
                amount=1500.50,  # type: ignore[arg-type]
                currency="USD",
                recipient_account="ACC-001",
                idempotency_key="idemp-key-002",
            )

    @pytest.mark.unit
    def test_disbursement_request_non_positive_amount(self) -> None:
        """Verify non-positive amounts are rejected."""
        with pytest.raises(ValidationError):
            DisbursementRequest(
                application_id=uuid.uuid4(),
                amount=Decimal("0.00"),
                currency="USD",
                recipient_account="ACC-001",
                idempotency_key="idemp-key-003",
            )


class TestSimulatedDisbursementProvider:
    """Unit tests for SimulatedDisbursementProvider payment execution and idempotency."""

    @pytest.mark.unit
    def test_simulated_disbursement_success(self) -> None:
        """Verify default simulation succeeds with generated provider_transaction_id."""
        provider = SimulatedDisbursementProvider()
        assert isinstance(provider, DisbursementProvider)

        req = DisbursementRequest(
            application_id=uuid.uuid4(),
            amount=Decimal("25000.00"),
            currency="USD",
            recipient_account="ACC-12345",
            idempotency_key="idemp-succ-001",
        )
        result = provider.disburse(req)

        assert result.status == DisbursementStatus.COMPLETED
        assert result.amount == Decimal("25000.00")
        assert result.provider_transaction_id is not None
        assert result.provider_transaction_id.startswith("sim_tx_")
        assert result.error_message is None
        assert isinstance(result.disbursed_at, datetime)

    @pytest.mark.unit
    def test_simulated_disbursement_idempotency(self) -> None:
        """Verify calling disburse with the same idempotency key returns the cached result."""
        provider = SimulatedDisbursementProvider()
        req = DisbursementRequest(
            application_id=uuid.uuid4(),
            amount=Decimal("18000.00"),
            currency="USD",
            recipient_account="ACC-12345",
            idempotency_key="idemp-cached-001",
        )
        result1 = provider.disburse(req)
        result2 = provider.disburse(req)

        assert result1.provider_transaction_id == result2.provider_transaction_id
        assert result1.disbursed_at == result2.disbursed_at
        assert result1.status == result2.status

    @pytest.mark.unit
    def test_simulated_disbursement_failure_mode(self) -> None:
        """Verify configured failure mode returns FAILED status and error message."""
        provider = SimulatedDisbursementProvider(
            always_fail=True, failure_message="Insufficient treasury balance"
        )
        req = DisbursementRequest(
            application_id=uuid.uuid4(),
            amount=Decimal("5000.00"),
            currency="USD",
            recipient_account="ACC-FAIL",
            idempotency_key="idemp-fail-001",
        )
        result = provider.disburse(req)

        assert result.status == DisbursementStatus.FAILED
        assert result.error_message == "Insufficient treasury balance"
        assert result.provider_transaction_id is None
        assert result.disbursed_at is None

    @pytest.mark.unit
    def test_simulated_disbursement_timeout_mode(self) -> None:
        """Verify configured timeout mode returns TIMEOUT status."""
        provider = SimulatedDisbursementProvider(always_timeout=True)
        req = DisbursementRequest(
            application_id=uuid.uuid4(),
            amount=Decimal("10000.00"),
            currency="USD",
            recipient_account="ACC-TIMEOUT",
            idempotency_key="idemp-timeout-001",
        )
        result = provider.disburse(req)

        assert result.status == DisbursementStatus.TIMEOUT
        assert result.error_message == "Gateway connection timeout"
        assert result.provider_transaction_id is None
