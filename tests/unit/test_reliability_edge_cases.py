"""Unit tests for system reliability, fault injection, and financial edge cases (Cycle 7.1)."""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from financeflow.core.exceptions import (
    DisbursementExecutionError,
    DuplicateDisbursementError,
    DuplicateSettlementError,
)
from financeflow.integrations.disbursement.provider import (
    DisbursementResult,
    DisbursementStatus,
)
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.services.disbursement import DisbursementService
from financeflow.services.financing import FinancingService
from financeflow.services.settlement import SettlementService


class TestReliabilityEdgeCases:
    """Reliability and boundary tests for disbursement, settlement, and financing."""

    @pytest.mark.unit
    def test_disbursement_wraps_provider_network_exception(self) -> None:
        """Verify unhandled provider network exceptions are caught, audited, and mapped."""
        session = MagicMock()
        financing_repo = MagicMock()
        disbursement_repo = MagicMock()
        invoice_repo = MagicMock()
        ledger_service = MagicMock()
        audit_repo = MagicMock()
        provider = MagicMock()

        # Simulate unexpected network socket/timeout error in provider
        provider.disburse.side_effect = ConnectionResetError("Connection reset by peer")

        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("50000.00"),
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
            status=FinancingStatus.APPROVED.value,
        )
        financing_repo.get_by_id.return_value = application
        disbursement_repo.get_by_idempotency_key.return_value = None
        disbursement_repo.get_by_application_id.return_value = None

        service = DisbursementService(
            session=session,
            financing_repo=financing_repo,
            disbursement_repo=disbursement_repo,
            invoice_repo=invoice_repo,
            ledger_service=ledger_service,
            provider=provider,
            audit_repo=audit_repo,
        )

        with pytest.raises(DisbursementExecutionError, match="Connection reset by peer"):
            service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-FAIL-TEST",
                idempotency_key="idemp-net-fail",
            )

        # Audit log must be recorded
        audit_repo.create.assert_called_once()
        audit_entry = audit_repo.create.call_args[0][0]
        assert audit_entry.application_id == app_id
        assert "Connection reset by peer" in audit_entry.reason
        session.commit.assert_called()

    @pytest.mark.unit
    def test_disbursement_audit_commit_error_triggers_rollback(self) -> None:
        """Verify session rollback occurs if audit commit raises during failure handling."""
        session = MagicMock()
        session.commit.side_effect = RuntimeError("DB commit failed")
        financing_repo = MagicMock()
        disbursement_repo = MagicMock()
        invoice_repo = MagicMock()
        ledger_service = MagicMock()
        audit_repo = MagicMock()
        provider = MagicMock()

        provider.disburse.side_effect = TimeoutError("Gateway timeout")

        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            approved_amount=Decimal("8000.00"),
            fee_amount=Decimal("240.00"),
            net_disbursement_amount=Decimal("7760.00"),
            status=FinancingStatus.APPROVED.value,
        )
        financing_repo.get_by_id.return_value = application
        disbursement_repo.get_by_idempotency_key.return_value = None
        disbursement_repo.get_by_application_id.return_value = None

        service = DisbursementService(
            session=session,
            financing_repo=financing_repo,
            disbursement_repo=disbursement_repo,
            invoice_repo=invoice_repo,
            ledger_service=ledger_service,
            provider=provider,
            audit_repo=audit_repo,
        )

        with pytest.raises(DisbursementExecutionError):
            service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-ROLLBACK-TEST",
                idempotency_key="idemp-rb-test",
            )

        session.rollback.assert_called()

    @pytest.mark.unit
    def test_disbursement_rejects_idempotency_key_payload_mismatch(self) -> None:
        """Verify reusing an idempotency key with different payload raises duplicate error."""
        session = MagicMock()
        financing_repo = MagicMock()
        disbursement_repo = MagicMock()
        invoice_repo = MagicMock()
        ledger_service = MagicMock()
        audit_repo = MagicMock()
        provider = MagicMock()

        app_id1 = uuid.uuid4()
        app_id2 = uuid.uuid4()

        # Existing disbursement record with idempotency_key='shared-key'
        existing_disb = MagicMock()
        existing_disb.financing_application_id = app_id1
        existing_disb.recipient_account = "ACC-ORIGINAL"
        existing_disb.idempotency_key = "shared-key"
        disbursement_repo.get_by_idempotency_key.return_value = existing_disb

        service = DisbursementService(
            session=session,
            financing_repo=financing_repo,
            disbursement_repo=disbursement_repo,
            invoice_repo=invoice_repo,
            ledger_service=ledger_service,
            provider=provider,
            audit_repo=audit_repo,
        )

        # Replaying for the SAME application and account returns existing (safe replay)
        replay = service.execute_disbursement(
            application_id=app_id1,
            recipient_account="ACC-ORIGINAL",
            idempotency_key="shared-key",
        )
        assert replay is existing_disb

        # Replaying with a DIFFERENT application_id must raise DuplicateDisbursementError
        with pytest.raises(DuplicateDisbursementError, match="different application or recipient"):
            service.execute_disbursement(
                application_id=app_id2,
                recipient_account="ACC-ORIGINAL",
                idempotency_key="shared-key",
            )

        # Replaying with a DIFFERENT recipient_account must raise DuplicateDisbursementError
        with pytest.raises(DuplicateDisbursementError, match="different application or recipient"):
            service.execute_disbursement(
                application_id=app_id1,
                recipient_account="ACC-DIFFERENT",
                idempotency_key="shared-key",
            )

    @pytest.mark.unit
    def test_settlement_rejects_idempotency_key_payload_mismatch(self) -> None:
        """Verify reusing an idempotency key with different payload raises duplicate error."""
        session = MagicMock()
        financing_repo = MagicMock()
        settlement_repo = MagicMock()
        invoice_repo = MagicMock()
        ledger_service = MagicMock()
        audit_repo = MagicMock()

        app_id = uuid.uuid4()
        other_app_id = uuid.uuid4()

        existing_settlement = MagicMock()
        existing_settlement.financing_application_id = app_id
        existing_settlement.repayment_amount = Decimal("30000.00")
        existing_settlement.idempotency_key = "settle-idemp-1"
        settlement_repo.get_by_idempotency_key.return_value = existing_settlement

        service = SettlementService(
            session=session,
            financing_repo=financing_repo,
            settlement_repo=settlement_repo,
            invoice_repo=invoice_repo,
            ledger_service=ledger_service,
            audit_repo=audit_repo,
        )

        # Same parameters: safe replay
        replay = service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("30000.00"),
            idempotency_key="settle-idemp-1",
        )
        assert replay is existing_settlement

        # Mismatched amount: must raise
        with pytest.raises(DuplicateSettlementError, match="different parameters"):
            service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("20000.00"),
                idempotency_key="settle-idemp-1",
            )

        # Mismatched application_id: must raise
        with pytest.raises(DuplicateSettlementError, match="different parameters"):
            service.execute_settlement(
                application_id=other_app_id,
                repayment_amount=Decimal("30000.00"),
                idempotency_key="settle-idemp-1",
            )

    @pytest.mark.unit
    def test_disbursement_uses_for_update_lock(self) -> None:
        """Verify disbursement service fetches the financing application with row-level lock."""
        session = MagicMock()
        financing_repo = MagicMock()
        disbursement_repo = MagicMock()
        invoice_repo = MagicMock()
        ledger_service = MagicMock()
        audit_repo = MagicMock()
        provider = MagicMock()

        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("50000.00"),
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
            status=FinancingStatus.APPROVED.value,
        )
        financing_repo.get_by_id.return_value = application
        disbursement_repo.get_by_idempotency_key.return_value = None
        disbursement_repo.get_by_application_id.return_value = None
        provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=Decimal("38800.00"),
            provider_transaction_id="tx_123",
        )

        service = DisbursementService(
            session=session,
            financing_repo=financing_repo,
            disbursement_repo=disbursement_repo,
            invoice_repo=invoice_repo,
            ledger_service=ledger_service,
            provider=provider,
            audit_repo=audit_repo,
        )

        service.execute_disbursement(
            application_id=app_id,
            recipient_account="ACC-1",
            idempotency_key="idemp-lock-1",
        )

        # get_by_id must be called with for_update=True
        financing_repo.get_by_id.assert_called_once_with(app_id, for_update=True)

    @pytest.mark.unit
    def test_financing_approval_uses_for_update_lock(self) -> None:
        """Verify financing approval fetches application with row-level lock."""
        session = MagicMock()
        financing_repo = MagicMock()
        invoice_repo = MagicMock()
        business_repo = MagicMock()

        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("50000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED.value,
        )
        financing_repo.get_by_id.return_value = application
        invoice = MagicMock()
        invoice_repo.get_by_id.return_value = invoice

        service = FinancingService(
            session=session,
            financing_repo=financing_repo,
            invoice_repo=invoice_repo,
            business_repo=business_repo,
        )

        service.approve_application(app_id)

        # get_by_id must be called with for_update=True
        financing_repo.get_by_id.assert_called_once_with(app_id, for_update=True)

    @pytest.mark.unit
    def test_boundary_financial_terms_calculations(self) -> None:
        """Verify calculations at boundary conditions: $1.00 minimums, 100% advance, 0% fee."""
        session = MagicMock()
        financing_repo = MagicMock()
        invoice_repo = MagicMock()
        business_repo = MagicMock()

        service = FinancingService(
            session=session,
            financing_repo=financing_repo,
            invoice_repo=invoice_repo,
            business_repo=business_repo,
        )

        # Scenario 1: Minimum $1.00 with 100% advance rate and 0% fee
        app_id_min = uuid.uuid4()
        app_min = FinancingApplication(
            id=app_id_min,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("1.00"),
            advance_rate=Decimal("1.0000"),
            fee_rate=Decimal("0.0000"),
            status=FinancingStatus.SUBMITTED.value,
        )
        financing_repo.get_by_id.return_value = app_min
        invoice_repo.get_by_id.return_value = MagicMock()

        approved_min = service.approve_application(app_id_min)
        assert approved_min.approved_amount == Decimal("1.00")
        assert approved_min.fee_amount == Decimal("0.00")
        assert approved_min.net_disbursement_amount == Decimal("1.00")

        # Scenario 2: Odd fraction requiring deterministic ROUND_HALF_UP
        # $100.05 requested at 85.50% advance rate = $85.54275 -> quantizes to $85.54
        # 3.25% fee on $85.54 = $2.78005 -> quantizes to $2.78
        # Net disbursement = $85.54 - $2.78 = $82.76
        app_id_odd = uuid.uuid4()
        app_odd = FinancingApplication(
            id=app_id_odd,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("100.05"),
            advance_rate=Decimal("0.8550"),
            fee_rate=Decimal("0.0325"),
            status=FinancingStatus.SUBMITTED.value,
        )
        financing_repo.get_by_id.return_value = app_odd

        approved_odd = service.approve_application(app_id_odd)
        assert approved_odd.approved_amount == Decimal("85.54")
        assert approved_odd.fee_amount == Decimal("2.78")
        assert approved_odd.net_disbursement_amount == Decimal("82.76")
