import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateFinancingError,
    FinancingApplicationNotFoundError,
    InvalidFinancingAmountError,
    InvalidFinancingStateTransitionError,
    InvalidFinancingTermsError,
    InvoiceNotEligibleError,
    InvoiceNotFoundError,
)
from financeflow.models.business import Business, BusinessStatus
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.services.financing import FinancingService, get_financing_service


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy Session."""
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
def mock_business_repo():
    """Mock BusinessRepository."""
    return MagicMock()


@pytest.fixture
def financing_service(mock_session, mock_financing_repo, mock_invoice_repo, mock_business_repo):
    """FinancingService instance with injected mock dependencies."""
    return FinancingService(
        session=mock_session,
        financing_repo=mock_financing_repo,
        invoice_repo=mock_invoice_repo,
        business_repo=mock_business_repo,
    )


class TestFinancingApplicationCreation:
    """Unit tests for FinancingService.create_application validating business rules."""

    @pytest.mark.unit
    def test_create_application_success(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify successful application creation validates invariants and commits."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        business = Business(
            id=b_id,
            tax_id="TAX-1",
            legal_name="Corp",
            status=BusinessStatus.ACTIVE,
        )
        invoice = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_business_repo.get_by_id.return_value = business
        mock_invoice_repo.get_by_id.return_value = invoice
        mock_financing_repo.get_active_by_invoice.return_value = None

        app = financing_service.create_application(
            business_id=b_id,
            invoice_id=inv_id,
            requested_amount=Decimal("8000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
        )

        mock_financing_repo.create.assert_called_once()
        mock_session.commit.assert_called_once()
        assert app.business_id == b_id
        assert app.invoice_id == inv_id
        assert app.requested_amount == Decimal("8000.00")
        assert app.status == FinancingStatus.SUBMITTED

    @pytest.mark.unit
    def test_create_application_business_not_found(
        self, financing_service: FinancingService, mock_business_repo: MagicMock
    ) -> None:
        """Verify BusinessNotFoundError is raised if business does not exist."""
        b_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = None

        with pytest.raises(BusinessNotFoundError, match=f"Business {b_id} not found"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=uuid.uuid4(),
                requested_amount=Decimal("5000.00"),
            )

    @pytest.mark.unit
    def test_create_application_business_inactive(
        self, financing_service: FinancingService, mock_business_repo: MagicMock
    ) -> None:
        """Verify BusinessInactiveError is raised if business is suspended."""
        b_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.SUSPENDED
        )

        with pytest.raises(BusinessInactiveError, match=f"Business {b_id} is not active"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=uuid.uuid4(),
                requested_amount=Decimal("5000.00"),
            )

    @pytest.mark.unit
    def test_create_application_invoice_not_found(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify InvoiceNotFoundError is raised if invoice does not exist."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = None

        with pytest.raises(InvoiceNotFoundError, match=f"Invoice {inv_id} not found"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("5000.00"),
            )

    @pytest.mark.unit
    def test_create_application_invoice_wrong_business(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify InvoiceNotEligibleError is raised if invoice belongs to a different business."""
        b_id = uuid.uuid4()
        other_b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=other_b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )

        with pytest.raises(InvoiceNotEligibleError, match="does not belong to"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("5000.00"),
            )

    @pytest.mark.unit
    def test_create_application_invoice_not_eligible_status(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify InvoiceNotEligibleError is raised if invoice is not in SUBMITTED status."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.PAID,
        )

        with pytest.raises(InvoiceNotEligibleError, match="Only SUBMITTED invoices"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("5000.00"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_amount", [Decimal("0.00"), Decimal("-100.00")])
    def test_create_application_non_positive_amount(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        bad_amount: Decimal,
    ) -> None:
        """Verify InvalidFinancingAmountError is raised when requested amount <= 0."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )

        with pytest.raises(InvalidFinancingAmountError, match="positive"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=bad_amount,
            )

    @pytest.mark.unit
    def test_create_application_requested_amount_exceeds_invoice(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify InvalidFinancingAmountError is raised when requested amount > invoice total."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )

        with pytest.raises(InvalidFinancingAmountError, match="cannot exceed invoice"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("15000.00"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("advance_rate", "fee_rate"),
        [
            (Decimal("0.0000"), Decimal("0.0300")),
            (Decimal("1.0500"), Decimal("0.0300")),
            (Decimal("0.8000"), Decimal("-0.0100")),
            (Decimal("0.8000"), Decimal("1.5000")),
        ],
    )
    def test_create_application_invalid_terms(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        advance_rate: Decimal,
        fee_rate: Decimal,
    ) -> None:
        """Verify InvalidFinancingTermsError is raised for out-of-bounds rates."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )

        with pytest.raises(InvalidFinancingTermsError):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("8000.00"),
                advance_rate=advance_rate,
                fee_rate=fee_rate,
            )

    @pytest.mark.unit
    def test_create_application_duplicate_active_application(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify DuplicateFinancingError is raised if invoice already has an active application."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_financing_repo.get_active_by_invoice.return_value = FinancingApplication(
            business_id=b_id,
            invoice_id=inv_id,
            requested_amount=Decimal("5000.00"),
            status=FinancingStatus.SUBMITTED,
        )

        with pytest.raises(DuplicateFinancingError, match="already has an active financing"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("8000.00"),
            )

    @pytest.mark.unit
    def test_create_application_commit_failure_rolls_back(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify session rollback when commit fails during application creation."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_financing_repo.get_active_by_invoice.return_value = None
        mock_session.commit.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError, match="DB error"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("8000.00"),
            )

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_create_application_unique_constraint_violation_translates(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify DB unique constraint violation translates to DuplicateFinancingError."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_financing_repo.get_active_by_invoice.return_value = None
        mock_session.commit.side_effect = IntegrityError(
            "uq_financing_active_invoice", params={}, orig=Exception("unique constraint")
        )

        with pytest.raises(DuplicateFinancingError, match="already has an active financing"):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("8000.00"),
            )

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_create_application_other_integrity_error_reraises(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify unrelated IntegrityError is re-raised and session rolled back."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_financing_repo.get_active_by_invoice.return_value = None
        mock_session.commit.side_effect = IntegrityError(
            "foreign key constraint", params={}, orig=Exception("fk error")
        )

        with pytest.raises(IntegrityError):
            financing_service.create_application(
                business_id=b_id,
                invoice_id=inv_id,
                requested_amount=Decimal("8000.00"),
            )

        mock_session.rollback.assert_called_once()


class TestFinancingApplicationDecision:
    """Unit tests for approval and rejection workflows."""

    @pytest.mark.unit
    def test_approve_application_success(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify application approval calculates exact financial precision amounts."""
        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        b_id = uuid.uuid4()

        app = FinancingApplication(
            id=app_id,
            business_id=b_id,
            invoice_id=inv_id,
            requested_amount=Decimal("10000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED,
        )
        invoice = Invoice(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_financing_repo.get_by_id.return_value = app
        mock_invoice_repo.get_by_id.return_value = invoice

        approved_app = financing_service.approve_application(app_id)

        # 10000.00 * 0.8000 = 8000.00 approved
        # 8000.00 * 0.0300 = 240.00 fee
        # 8000.00 - 240.00 = 7760.00 net disbursement
        assert approved_app.status == FinancingStatus.APPROVED
        assert approved_app.approved_amount == Decimal("8000.00")
        assert approved_app.fee_amount == Decimal("240.00")
        assert approved_app.net_disbursement_amount == Decimal("7760.00")
        assert invoice.status == InvoiceStatus.APPROVED
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_approve_application_not_found(
        self, financing_service: FinancingService, mock_financing_repo: MagicMock
    ) -> None:
        """Verify FinancingApplicationNotFoundError when application does not exist."""
        app_id = uuid.uuid4()
        mock_financing_repo.get_by_id.return_value = None

        with pytest.raises(
            FinancingApplicationNotFoundError,
            match=f"Application {app_id} not found",
        ):
            financing_service.approve_application(app_id)

    @pytest.mark.unit
    def test_approve_application_invalid_state_transition(
        self, financing_service: FinancingService, mock_financing_repo: MagicMock
    ) -> None:
        """Verify InvalidFinancingStateTransitionError if application is not in SUBMITTED state."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            status=FinancingStatus.APPROVED,
        )
        mock_financing_repo.get_by_id.return_value = app

        with pytest.raises(
            InvalidFinancingStateTransitionError,
            match="Cannot approve application",
        ):
            financing_service.approve_application(app_id)

    @pytest.mark.unit
    def test_approve_application_commit_failure_rolls_back(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_financing_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify rollback when commit fails during application approval."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED,
        )
        mock_financing_repo.get_by_id.return_value = app
        mock_invoice_repo.get_by_id.return_value = Invoice(
            id=app.invoice_id,
            business_id=app.business_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED,
        )
        mock_session.commit.side_effect = RuntimeError("DB connection lost")

        with pytest.raises(RuntimeError, match="DB connection lost"):
            financing_service.approve_application(app_id)

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_reject_application_success(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify application rejection records status and reason."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED,
        )
        mock_financing_repo.get_by_id.return_value = app

        rejected = financing_service.reject_application(app_id, reason="Debtor credit risk")

        assert rejected.status == FinancingStatus.REJECTED
        assert rejected.rejection_reason == "Debtor credit risk"
        mock_session.commit.assert_called_once()

    @pytest.mark.unit
    def test_reject_application_not_found(
        self, financing_service: FinancingService, mock_financing_repo: MagicMock
    ) -> None:
        """Verify FinancingApplicationNotFoundError when rejecting non-existent application."""
        app_id = uuid.uuid4()
        mock_financing_repo.get_by_id.return_value = None

        with pytest.raises(
            FinancingApplicationNotFoundError, match=f"Application {app_id} not found"
        ):
            financing_service.reject_application(app_id, reason="Reason")

    @pytest.mark.unit
    def test_reject_application_commit_failure_rolls_back(
        self,
        financing_service: FinancingService,
        mock_session: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify rollback when commit fails during application rejection."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED,
        )
        mock_financing_repo.get_by_id.return_value = app
        mock_session.commit.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError, match="DB error"):
            financing_service.reject_application(app_id, reason="Reason")

        mock_session.rollback.assert_called_once()

    @pytest.mark.unit
    def test_reject_application_invalid_state_transition(
        self, financing_service: FinancingService, mock_financing_repo: MagicMock
    ) -> None:
        """Verify state transition error if rejecting an already rejected application."""
        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("10000.00"),
            status=FinancingStatus.REJECTED,
        )
        mock_financing_repo.get_by_id.return_value = app

        with pytest.raises(InvalidFinancingStateTransitionError, match="Cannot reject application"):
            financing_service.reject_application(app_id, reason="Any reason")


class TestFinancingApplicationRetrieval:
    """Unit tests for query methods on FinancingService."""

    @pytest.mark.unit
    def test_get_application(
        self, financing_service: FinancingService, mock_financing_repo: MagicMock
    ) -> None:
        """Verify get_application retrieves application by ID."""
        app_id = uuid.uuid4()
        mock_financing_repo.get_by_id.return_value = FinancingApplication(
            id=app_id,
            business_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            requested_amount=Decimal("5000.00"),
        )
        app = financing_service.get_application(app_id)
        assert app is not None
        assert app.id == app_id

    @pytest.mark.unit
    def test_list_applications_by_business_success(
        self,
        financing_service: FinancingService,
        mock_business_repo: MagicMock,
        mock_financing_repo: MagicMock,
    ) -> None:
        """Verify list_applications_by_business returns list for existing business."""
        b_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=b_id, tax_id="TAX-1", legal_name="Corp", status=BusinessStatus.ACTIVE
        )
        mock_financing_repo.list_by_business.return_value = [
            FinancingApplication(
                business_id=b_id,
                invoice_id=uuid.uuid4(),
                requested_amount=Decimal("5000.00"),
            )
        ]
        results = financing_service.list_applications_by_business(b_id, limit=10, offset=0)
        assert len(results) == 1
        mock_financing_repo.list_by_business.assert_called_once_with(
            business_id=b_id, limit=10, offset=0
        )

    @pytest.mark.unit
    def test_list_applications_by_business_not_found(
        self, financing_service: FinancingService, mock_business_repo: MagicMock
    ) -> None:
        """Verify BusinessNotFoundError when listing applications for non-existent business."""
        b_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = None

        with pytest.raises(BusinessNotFoundError, match=f"Business {b_id} not found"):
            financing_service.list_applications_by_business(b_id)


class TestFinancingDependencyProvider:
    """Unit test for get_financing_service dependency provider."""

    @pytest.mark.unit
    def test_get_financing_service(self, mock_session: MagicMock) -> None:
        """Verify dependency provider creates FinancingService with session-injected repos."""
        service = get_financing_service(session=mock_session)
        assert isinstance(service, FinancingService)
        assert service._session == mock_session
