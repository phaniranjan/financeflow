import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from financeflow.core.exceptions import (
    DuplicateSettlementError,
    FinancingApplicationNotFoundError,
    InvalidSettlementAmountError,
    InvalidSettlementStateError,
)
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.models.settlement import Settlement, SettlementStatus
from financeflow.services.ledger import LedgerService
from financeflow.services.settlement import (
    SettlementService,
    get_settlement_service,
)


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy Session."""
    return MagicMock()


@pytest.fixture
def mock_settlement_repo():
    """Mock SettlementRepository."""
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
def mock_audit_repo():
    """Mock AuditRepository."""
    return MagicMock()


@pytest.fixture
def settlement_service(
    mock_session,
    mock_settlement_repo,
    mock_financing_repo,
    mock_invoice_repo,
    mock_ledger_service,
    mock_audit_repo,
):
    """SettlementService instance with injected mock dependencies."""
    return SettlementService(
        session=mock_session,
        settlement_repo=mock_settlement_repo,
        financing_repo=mock_financing_repo,
        invoice_repo=mock_invoice_repo,
        ledger_service=mock_ledger_service,
        audit_repo=mock_audit_repo,
    )


class TestExecuteSettlement:
    """Unit tests for SettlementService.execute_settlement."""

    @pytest.mark.unit
    def test_idempotency_replay(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """When an idempotency key was previously processed, return the existing settlement."""
        app_id = uuid.uuid4()
        existing = Settlement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            invoice_id=uuid.uuid4(),
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            net_reserve_refunded=Decimal("10000.00"),
            idempotency_key="idemp-settle-001",
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = existing

        result = settlement_service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("50000.00"),
            idempotency_key="idemp-settle-001",
        )

        assert result == existing
        mock_session.commit.assert_not_called()

    @pytest.mark.unit
    def test_application_not_found_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises FinancingApplicationNotFoundError if application does not exist."""
        app_id = uuid.uuid4()
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = None

        with pytest.raises(FinancingApplicationNotFoundError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-settle-new",
            )

    @pytest.mark.unit
    def test_application_already_settled_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises DuplicateSettlementError if application has already been settled."""
        app_id = uuid.uuid4()
        app = FinancingApplication(id=app_id, status=FinancingStatus.SETTLED.value)
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None

        with pytest.raises(DuplicateSettlementError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-settle-new",
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "invalid_status",
        [
            FinancingStatus.DRAFT.value,
            FinancingStatus.SUBMITTED.value,
            FinancingStatus.APPROVED.value,
            FinancingStatus.REJECTED.value,
        ],
    )
    def test_invalid_status_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        invalid_status: str,
    ) -> None:
        """Only applications in DISBURSED state can be settled."""
        app_id = uuid.uuid4()
        app = FinancingApplication(id=app_id, status=invalid_status)
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None

        with pytest.raises(InvalidSettlementStateError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-settle-new",
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "invalid_amount",
        [Decimal("0.00"), Decimal("-100.00")],
    )
    def test_non_positive_repayment_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        invalid_amount: Decimal,
    ) -> None:
        """Repayment amount must be strictly positive."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None

        with pytest.raises(InvalidSettlementAmountError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=invalid_amount,
                idempotency_key="idemp-settle-new",
            )

    @pytest.mark.unit
    def test_fee_exceeding_reserve_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Raises InvalidSettlementAmountError if settlement fee exceeds calculated reserve."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None

        with pytest.raises(InvalidSettlementAmountError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),  # Reserve is 10k
                settlement_fee=Decimal("12000.00"),  # Fee 12k > 10k reserve
                idempotency_key="idemp-settle-new",
            )

    @pytest.mark.unit
    def test_full_settlement_success(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_ledger_service: MagicMock,
        mock_audit_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify full settlement: principal cleared, reserve refunded, and ledger journalized."""
        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        app = FinancingApplication(
            id=app_id,
            invoice_id=inv_id,
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        invoice = Invoice(
            id=inv_id,
            status=InvoiceStatus.FINANCED.value,
        )

        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = invoice

        def mock_create_settlement(s: Settlement) -> Settlement:
            s.id = uuid.uuid4()
            return s

        mock_settlement_repo.create.side_effect = mock_create_settlement

        result = settlement_service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("50000.00"),
            settlement_fee=Decimal("100.00"),
            idempotency_key="idemp-settle-ok",
            correlation_id="corr-settle-01",
        )

        assert result is not None
        assert result.status == SettlementStatus.COMPLETED.value
        assert result.repayment_amount == Decimal("50000.00")
        assert result.principal_repaid == Decimal("40000.00")
        assert result.reserve_amount == Decimal("10000.00")
        assert result.settlement_fee == Decimal("100.00")
        assert result.net_reserve_refunded == Decimal("9900.00")

        # Application transitioned to SETTLED
        assert app.status == FinancingStatus.SETTLED.value

        # Invoice transitioned to PAID
        assert invoice.status == InvoiceStatus.PAID.value

        # Ledger transactions posted
        mock_ledger_service.post_settlement_transaction.assert_called_once_with(
            application_id=app_id,
            repayment_amount=Decimal("50000.00"),
            principal_amount=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
        )
        mock_ledger_service.post_reserve_release_transaction.assert_called_once_with(
            application_id=app_id,
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("100.00"),
            net_refund_amount=Decimal("9900.00"),
        )

        # Audit log written
        mock_audit_repo.create.assert_called_once()
        audit_call = mock_audit_repo.create.call_args[0][0]
        assert isinstance(audit_call, FinancingAuditLog)
        assert audit_call.application_id == app_id
        assert audit_call.from_status == FinancingStatus.DISBURSED.value
        assert audit_call.to_status == FinancingStatus.SETTLED.value
        assert audit_call.actor == "SETTLEMENT_SERVICE"
        assert audit_call.correlation_id == "corr-settle-01"

        # Session committed
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_shortfall_settlement_success(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_ledger_service: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """When repayment < approved_amount, marks SHORTFALL and skips reserve release."""
        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        app = FinancingApplication(
            id=app_id,
            invoice_id=inv_id,
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        invoice = Invoice(id=inv_id, status=InvoiceStatus.FINANCED.value)

        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = invoice

        def mock_create(s: Settlement) -> Settlement:
            s.id = uuid.uuid4()
            return s

        mock_settlement_repo.create.side_effect = mock_create

        result = settlement_service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("35000.00"),  # Less than 40k principal
            idempotency_key="idemp-shortfall",
        )

        assert result.status == SettlementStatus.SHORTFALL.value
        assert result.principal_repaid == Decimal("35000.00")
        assert result.reserve_amount == Decimal("0.00")
        assert result.net_reserve_refunded == Decimal("0.00")

        mock_ledger_service.post_settlement_transaction.assert_called_once_with(
            application_id=app_id,
            repayment_amount=Decimal("35000.00"),
            principal_amount=Decimal("35000.00"),
            reserve_amount=Decimal("0.00"),
        )
        mock_ledger_service.post_reserve_release_transaction.assert_not_called()
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_integrity_error_mapped_to_duplicate(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Unique constraint conflict raises DuplicateSettlementError."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            invoice_id=uuid.uuid4(),
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = Invoice(id=app.invoice_id)

        orig_exc = Exception(
            'duplicate key value violates unique constraint "ix_settlements_idempotency_key"'
        )
        mock_settlement_repo.create.side_effect = IntegrityError("statement", {}, orig_exc)

        with pytest.raises(DuplicateSettlementError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-dup",
            )
        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_non_unique_integrity_error_re_raises(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """IntegrityError not related to unique constraint is rolled back and re-raised."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            status=FinancingStatus.DISBURSED.value,
            invoice_id=uuid.uuid4(),
            approved_amount=Decimal("40000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = Invoice(id=app.invoice_id)

        orig_exc = Exception("check constraint violation ck_some_constraint")
        mock_settlement_repo.create.side_effect = IntegrityError("statement", {}, orig_exc)

        with pytest.raises(IntegrityError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-non-unique-int",
            )
        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_unexpected_exception_rolls_back(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Unexpected exception rolls back session and re-raises."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            invoice_id=uuid.uuid4(),
            status=FinancingStatus.DISBURSED.value,
            approved_amount=Decimal("40000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.get_by_application_id.return_value = None
        mock_invoice_repo.get_by_id.return_value = Invoice(id=app.invoice_id)

        mock_settlement_repo.create.side_effect = RuntimeError("DB down")

        with pytest.raises(RuntimeError):
            settlement_service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("50000.00"),
                idempotency_key="idemp-err",
            )
        mock_session.rollback.assert_called_once()


class TestSettlementRetrieval:
    """Unit tests for get_settlement and get_settlement_by_application."""

    @pytest.mark.unit
    def test_get_settlement(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
    ) -> None:
        """Retrieves settlement by primary ID."""
        s_id = uuid.uuid4()
        s = Settlement(id=s_id)
        mock_settlement_repo.get_by_id.return_value = s

        assert settlement_service.get_settlement(s_id) == s

    @pytest.mark.unit
    def test_get_settlement_by_application(
        self,
        settlement_service: SettlementService,
        mock_settlement_repo: MagicMock,
    ) -> None:
        """Retrieves settlement by financing application ID."""
        app_id = uuid.uuid4()
        s = Settlement(id=uuid.uuid4(), financing_application_id=app_id)
        mock_settlement_repo.get_by_application_id.return_value = s

        assert settlement_service.get_settlement_by_application(app_id) == s


class TestGetSettlementServiceDependency:
    """Unit tests for get_settlement_service dependency factory."""

    @pytest.mark.unit
    def test_get_settlement_service(
        self, mock_session: MagicMock, mock_ledger_service: MagicMock
    ) -> None:
        """Dependency factory returns SettlementService with wired dependencies."""
        service = get_settlement_service(session=mock_session, ledger_service=mock_ledger_service)
        assert isinstance(service, SettlementService)
        assert service._session == mock_session
