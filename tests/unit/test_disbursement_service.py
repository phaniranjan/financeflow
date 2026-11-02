import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from financeflow.core.exceptions import (
    DisbursementExecutionError,
    DuplicateDisbursementError,
    FinancingApplicationNotFoundError,
    InvalidDisbursementStateError,
)
from financeflow.integrations.disbursement.provider import (
    DisbursementResult,
    DisbursementStatus,
)
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.disbursement import Disbursement
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.services.disbursement import (
    DisbursementService,
    get_disbursement_service,
)
from financeflow.services.ledger import LedgerService


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy Session."""
    return MagicMock()


@pytest.fixture
def mock_disbursement_repo():
    """Mock DisbursementRepository."""
    return MagicMock()


@pytest.fixture
def mock_financing_repo():
    """Mock FinancingRepository."""
    return MagicMock()


@pytest.fixture
def mock_invoice_repo():
    """Mock InvoiceRepository."""
    return MagicMock()


@pytest.fixture
def mock_ledger_service():
    """Mock LedgerService."""
    return MagicMock(spec=LedgerService)


@pytest.fixture
def mock_provider():
    """Mock DisbursementProvider."""
    return MagicMock()


@pytest.fixture
def mock_audit_repo():
    """Mock AuditRepository."""
    return MagicMock()


@pytest.fixture
def disbursement_service(
    mock_session,
    mock_disbursement_repo,
    mock_financing_repo,
    mock_invoice_repo,
    mock_ledger_service,
    mock_provider,
    mock_audit_repo,
):
    """DisbursementService with mock dependencies."""
    return DisbursementService(
        session=mock_session,
        disbursement_repo=mock_disbursement_repo,
        financing_repo=mock_financing_repo,
        invoice_repo=mock_invoice_repo,
        ledger_service=mock_ledger_service,
        provider=mock_provider,
        audit_repo=mock_audit_repo,
    )


class TestExecuteDisbursement:
    """Unit tests for DisbursementService.execute_disbursement."""

    @pytest.mark.unit
    def test_idempotency_replay(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """When an idempotency key was previously used, return the existing disbursement."""
        app_id = uuid.uuid4()
        existing_disbursement = Disbursement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            idempotency_key="idemp-123",
            amount=Decimal("38800.00"),
            recipient_account="ACC-999",
            status=DisbursementStatus.COMPLETED.value,
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = existing_disbursement

        result = disbursement_service.execute_disbursement(
            application_id=app_id,
            recipient_account="ACC-999",
            idempotency_key="idemp-123",
        )

        assert result == existing_disbursement
        mock_provider.disburse.assert_not_called()
        mock_session.commit.assert_not_called()

    @pytest.mark.unit
    def test_application_not_found_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises FinancingApplicationNotFoundError if application does not exist."""
        app_id = uuid.uuid4()
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = None

        with pytest.raises(FinancingApplicationNotFoundError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-999",
                idempotency_key="idemp-123",
            )
        assert f"Application {app_id} not found" in str(exc_info.value)

    @pytest.mark.unit
    def test_application_already_disbursed_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises DuplicateDisbursementError if application already has a disbursement."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.APPROVED.value,
        )
        existing_disb = Disbursement(id=uuid.uuid4(), financing_application_id=app_id)

        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = existing_disb

        with pytest.raises(DuplicateDisbursementError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-999",
                idempotency_key="idemp-new",
            )
        assert f"Application {app_id} has already been disbursed" in str(exc_info.value)

    @pytest.mark.unit
    def test_application_status_disbursed_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises DuplicateDisbursementError if application status is DISBURSED."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.DISBURSED.value,
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        with pytest.raises(DuplicateDisbursementError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-999",
                idempotency_key="idemp-new",
            )
        assert f"Application {app_id} has already been disbursed" in str(exc_info.value)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "invalid_status",
        [
            FinancingStatus.DRAFT.value,
            FinancingStatus.SUBMITTED.value,
            FinancingStatus.REJECTED.value,
        ],
    )
    def test_invalid_status_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        invalid_status: str,
    ) -> None:
        """Only APPROVED applications can be disbursed."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=invalid_status,
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        with pytest.raises(InvalidDisbursementStateError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-999",
                idempotency_key="idemp-new",
            )
        assert f"Cannot disburse application in '{invalid_status}' status" in str(exc_info.value)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("net", "approved", "fee"),
        [
            (None, Decimal("40000.00"), Decimal("1200.00")),
            (Decimal("38800.00"), None, Decimal("1200.00")),
            (Decimal("38800.00"), Decimal("40000.00"), None),
        ],
    )
    def test_unfinalized_amounts_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        net: Decimal | None,
        approved: Decimal | None,
        fee: Decimal | None,
    ) -> None:
        """Raises InvalidDisbursementStateError if amounts are not populated on application."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.APPROVED.value,
            net_disbursement_amount=net,
            approved_amount=approved,
            fee_amount=fee,
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        with pytest.raises(InvalidDisbursementStateError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-999",
                idempotency_key="idemp-new",
            )
        assert "Application financial amounts are not finalized" in str(exc_info.value)

    @pytest.mark.unit
    def test_provider_failure_records_audit_and_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_audit_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Provider failure records an audit log and raises DisbursementExecutionError."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.FAILED,
            amount=Decimal("38800.00"),
            error_message="Bank rail rejected: invalid account number",
        )

        with pytest.raises(DisbursementExecutionError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-INVALID",
                idempotency_key="idemp-fail",
                correlation_id="corr-audit-fail",
            )

        assert "Bank rail rejected" in str(exc_info.value)
        mock_audit_repo.create.assert_called_once()
        audit_call = mock_audit_repo.create.call_args[0][0]
        assert isinstance(audit_call, FinancingAuditLog)
        assert audit_call.application_id == app_id
        assert audit_call.actor == "DISBURSEMENT_GATEWAY"
        assert audit_call.correlation_id == "corr-audit-fail"
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_provider_timeout_records_audit_and_raises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_audit_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Provider timeout records audit log and raises DisbursementExecutionError."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.TIMEOUT,
            amount=Decimal("38800.00"),
            error_message=None,  # triggers default error message
        )

        with pytest.raises(DisbursementExecutionError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-TIMEOUT",
                idempotency_key="idemp-timeout",
            )

        assert "Disbursement provider rejected transfer" in str(exc_info.value)
        mock_audit_repo.create.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_provider_failure_audit_commit_error_rollbacks(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """If committing the failure audit log encounters an error, rollback is called."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.FAILED,
            amount=Decimal("38800.00"),
            error_message="Network error",
        )
        mock_session.commit.side_effect = RuntimeError("DB disconnect")

        with pytest.raises(DisbursementExecutionError):
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-ERR",
                idempotency_key="idemp-err",
            )

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_execute_disbursement_success(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_ledger_service: MagicMock,
        mock_provider: MagicMock,
        mock_audit_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify successful execution of disbursement with state transitions and ledger."""
        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        now = datetime.now(UTC)

        application = FinancingApplication(
            id=app_id,
            invoice_id=inv_id,
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        invoice = Invoice(
            id=inv_id,
            status=InvoiceStatus.APPROVED.value,
        )

        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = invoice

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=Decimal("38800.00"),
            provider_transaction_id="TX-PAY-9999",
            disbursed_at=now,
        )

        def mock_create_disbursement(disb: Disbursement) -> Disbursement:
            disb.id = uuid.uuid4()
            return disb

        mock_disbursement_repo.create.side_effect = mock_create_disbursement

        result = disbursement_service.execute_disbursement(
            application_id=app_id,
            recipient_account="ACC-VALID-01",
            idempotency_key="idemp-success",
            correlation_id="corr-test-01",
        )

        assert result is not None
        assert result.status == DisbursementStatus.COMPLETED.value
        assert result.provider_transaction_id == "TX-PAY-9999"
        assert result.amount == Decimal("38800.00")
        assert result.recipient_account == "ACC-VALID-01"

        # Application transitioned to DISBURSED
        assert application.status == FinancingStatus.DISBURSED.value

        # Underlying invoice transitioned to FINANCED
        assert invoice.status == InvoiceStatus.FINANCED.value

        # Double-entry ledger posted
        mock_ledger_service.post_disbursement_transaction.assert_called_once_with(
            application_id=app_id,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_amount=Decimal("38800.00"),
        )

        # Audit log written
        mock_audit_repo.create.assert_called_once()
        audit_call = mock_audit_repo.create.call_args[0][0]
        assert audit_call.application_id == app_id
        assert audit_call.from_status == FinancingStatus.APPROVED.value
        assert audit_call.to_status == FinancingStatus.DISBURSED.value
        assert audit_call.actor == "DISBURSEMENT_SERVICE"
        assert audit_call.correlation_id == "corr-test-01"

        # Atomic commit
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_integrity_error_unique_constraint_mapped_to_duplicate(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """IntegrityError from unique constraint translates to DuplicateDisbursementError."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            invoice_id=uuid.uuid4(),
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=Decimal("38800.00"),
            provider_transaction_id="TX-PAY-8888",
        )

        orig_exc = Exception(
            'duplicate key value violates unique constraint "ix_disbursements_idempotency_key"'
        )
        mock_disbursement_repo.create.side_effect = IntegrityError("statement", {}, orig_exc)

        with pytest.raises(DuplicateDisbursementError) as exc_info:
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-DUPE",
                idempotency_key="idemp-conflict",
            )

        assert f"Disbursement conflict for application {app_id}" in str(exc_info.value)
        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_integrity_error_other_reraises(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Generic IntegrityError re-raises after session rollback."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            invoice_id=uuid.uuid4(),
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=Decimal("38800.00"),
            provider_transaction_id="TX-PAY-8888",
        )

        orig_exc = Exception("foreign key violation")
        mock_disbursement_repo.create.side_effect = IntegrityError("statement", {}, orig_exc)

        with pytest.raises(IntegrityError):
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-FK",
                idempotency_key="idemp-fk",
            )

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_unexpected_exception_rolls_back(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_provider: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Unexpected exceptions cause session rollback and re-raise."""
        app_id = uuid.uuid4()
        application = FinancingApplication(
            id=app_id,
            invoice_id=uuid.uuid4(),
            status=FinancingStatus.APPROVED.value,
            approved_amount=Decimal("40000.00"),
            fee_amount=Decimal("1200.00"),
            net_disbursement_amount=Decimal("38800.00"),
        )
        mock_disbursement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = application
        mock_disbursement_repo.get_by_application_id.return_value = None

        mock_provider.disburse.return_value = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=Decimal("38800.00"),
            provider_transaction_id="TX-PAY-8888",
        )

        mock_disbursement_repo.create.side_effect = RuntimeError("Fatal crash")

        with pytest.raises(RuntimeError):
            disbursement_service.execute_disbursement(
                application_id=app_id,
                recipient_account="ACC-UNEXP",
                idempotency_key="idemp-unexp",
            )

        mock_session.rollback.assert_called_once()


class TestDisbursementRetrieval:
    """Unit tests for get_disbursement and get_disbursement_by_application."""

    @pytest.mark.unit
    def test_get_disbursement(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
    ) -> None:
        """Retrieves disbursement by primary key."""
        disb_id = uuid.uuid4()
        disb = Disbursement(id=disb_id)
        mock_disbursement_repo.get_by_id.return_value = disb

        result = disbursement_service.get_disbursement(disb_id)
        assert result == disb
        mock_disbursement_repo.get_by_id.assert_called_once_with(disb_id)

    @pytest.mark.unit
    def test_get_disbursement_by_application(
        self,
        disbursement_service: DisbursementService,
        mock_disbursement_repo: MagicMock,
    ) -> None:
        """Retrieves disbursement by application ID."""
        app_id = uuid.uuid4()
        disb = Disbursement(id=uuid.uuid4(), financing_application_id=app_id)
        mock_disbursement_repo.get_by_application_id.return_value = disb

        result = disbursement_service.get_disbursement_by_application(app_id)
        assert result == disb
        mock_disbursement_repo.get_by_application_id.assert_called_once_with(app_id)


class TestGetDisbursementServiceDependency:
    """Unit tests for get_disbursement_service dependency injection."""

    @pytest.mark.unit
    def test_get_disbursement_service(
        self, mock_session: MagicMock, mock_ledger_service: MagicMock
    ) -> None:
        """Dependency factory returns DisbursementService with all dependencies wired."""
        service = get_disbursement_service(session=mock_session, ledger_service=mock_ledger_service)
        assert isinstance(service, DisbursementService)
        assert service._session == mock_session
        assert service._ledger_service == mock_ledger_service
