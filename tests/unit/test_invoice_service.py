import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateInvoiceNumberError,
    InvalidInvoiceAmountError,
    InvalidInvoiceDateError,
)
from financeflow.models.business import Business
from financeflow.models.invoice import Invoice
from financeflow.services.invoice import InvoiceService, get_invoice_service


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy Session."""
    session = MagicMock()
    return session


@pytest.fixture
def mock_invoice_repo():
    """Mock InvoiceRepository."""
    return MagicMock()


@pytest.fixture
def mock_business_repo():
    """Mock BusinessRepository."""
    return MagicMock()


@pytest.fixture
def invoice_service(mock_session, mock_invoice_repo, mock_business_repo):
    """InvoiceService instance with injected mock dependencies."""
    return InvoiceService(
        session=mock_session,
        invoice_repo=mock_invoice_repo,
        business_repo=mock_business_repo,
    )


class TestInvoiceServiceCreation:
    """Unit tests for InvoiceService.create_invoice enforcing business invariants."""

    @pytest.mark.unit
    def test_create_invoice_success(
        self,
        invoice_service: InvoiceService,
        mock_session: MagicMock,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify successful invoice creation validates business and commits transaction."""
        business_id = uuid.uuid4()
        active_business = Business(
            id=business_id,
            tax_id="TAX-ACTIVE-1",
            legal_name="Active Corp",
            status="ACTIVE",
        )
        mock_business_repo.get_by_id.return_value = active_business
        mock_invoice_repo.get_by_number.return_value = None

        invoice_amount = Decimal("15000.00")
        created_invoice = invoice_service.create_invoice(
            business_id=business_id,
            invoice_number="INV-2026-001",
            debtor_name="Target Debtor LLC",
            amount=invoice_amount,
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )

        mock_business_repo.get_by_id.assert_called_once_with(business_id)
        mock_invoice_repo.get_by_number.assert_called_once_with(business_id, "INV-2026-001")
        mock_invoice_repo.create.assert_called_once()
        mock_session.commit.assert_called_once()

        assert created_invoice.business_id == business_id
        assert created_invoice.invoice_number == "INV-2026-001"
        assert created_invoice.amount == Decimal("15000.00")
        assert created_invoice.status == "SUBMITTED"

    @pytest.mark.unit
    def test_create_invoice_business_not_found(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify BusinessNotFoundError is raised when business does not exist."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = None

        with pytest.raises(BusinessNotFoundError, match=f"Business {business_id} not found"):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="INV-001",
                debtor_name="Debtor",
                amount=Decimal("100.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

        mock_session.commit.assert_not_called()

    @pytest.mark.unit
    def test_create_invoice_business_inactive(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify BusinessInactiveError is raised when business is SUSPENDED or INACTIVE."""
        business_id = uuid.uuid4()
        suspended_business = Business(
            id=business_id,
            tax_id="TAX-SUSPENDED",
            legal_name="Suspended Corp",
            status="SUSPENDED",
        )
        mock_business_repo.get_by_id.return_value = suspended_business

        with pytest.raises(BusinessInactiveError, match=f"Business {business_id} is not active"):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="INV-001",
                debtor_name="Debtor",
                amount=Decimal("100.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

        mock_session.commit.assert_not_called()

    @pytest.mark.unit
    def test_create_invoice_duplicate_number(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify DuplicateInvoiceNumberError is raised when invoice_number already exists."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=business_id,
            tax_id="TAX-1",
            legal_name="Corp",
            status="ACTIVE",
        )
        mock_invoice_repo.get_by_number.return_value = Invoice(
            business_id=business_id,
            invoice_number="DUP-001",
            debtor_name="Existing Debtor",
            amount=Decimal("500.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )

        with pytest.raises(
            DuplicateInvoiceNumberError,
            match="Invoice number 'DUP-001' already exists for this business",
        ):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="DUP-001",
                debtor_name="Debtor",
                amount=Decimal("100.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

        mock_session.commit.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_amount", [Decimal("0.00"), Decimal("-10.00")])
    def test_create_invoice_non_positive_amount(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        invalid_amount: Decimal,
    ) -> None:
        """Verify InvalidInvoiceAmountError is raised when amount <= 0."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=business_id, tax_id="TAX-1", legal_name="Corp", status="ACTIVE"
        )

        with pytest.raises(InvalidInvoiceAmountError, match="Invoice amount must be positive"):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="INV-001",
                debtor_name="Debtor",
                amount=invalid_amount,
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

    @pytest.mark.unit
    def test_create_invoice_due_date_before_issue_date(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
    ) -> None:
        """Verify InvalidInvoiceDateError is raised when due_date < issue_date."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=business_id, tax_id="TAX-1", legal_name="Corp", status="ACTIVE"
        )

        with pytest.raises(
            InvalidInvoiceDateError, match="Due date cannot precede invoice issue date"
        ):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="INV-001",
                debtor_name="Debtor",
                amount=Decimal("1000.00"),
                currency="USD",
                issue_date=date(2026, 12, 1),
                due_date=date(2026, 11, 1),
            )

    @pytest.mark.unit
    def test_create_invoice_commit_failure_rolls_back(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Verify session.rollback is executed when commit fails unexpectedly."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=business_id, tax_id="TAX-1", legal_name="Corp", status="ACTIVE"
        )
        mock_invoice_repo.get_by_number.return_value = None
        mock_session.commit.side_effect = RuntimeError("Database connection lost")

        with pytest.raises(RuntimeError, match="Database connection lost"):
            invoice_service.create_invoice(
                business_id=business_id,
                invoice_number="INV-FAIL-001",
                debtor_name="Debtor",
                amount=Decimal("5000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

        mock_session.rollback.assert_called_once()


class TestInvoiceServiceRetrieval:
    """Unit tests for invoice querying methods on InvoiceService."""

    @pytest.mark.unit
    def test_get_invoice_by_id(
        self,
        invoice_service: InvoiceService,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify getting an invoice delegates to the repository."""
        inv_id = uuid.uuid4()
        expected = Invoice(
            id=inv_id,
            business_id=uuid.uuid4(),
            invoice_number="INV-100",
            debtor_name="Debtor",
            amount=Decimal("500.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        mock_invoice_repo.get_by_id.return_value = expected

        result = invoice_service.get_invoice(inv_id)
        assert result is expected
        mock_invoice_repo.get_by_id.assert_called_once_with(inv_id)

    @pytest.mark.unit
    def test_list_invoices_validates_business_exists(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
        mock_invoice_repo: MagicMock,
    ) -> None:
        """Verify list_invoices validates business existence before returning invoices."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = Business(
            id=business_id, tax_id="TAX-1", legal_name="Corp", status="ACTIVE"
        )
        mock_invoice_repo.list_by_business.return_value = []

        result = invoice_service.list_invoices_by_business(business_id, limit=50, offset=0)
        assert result == []
        mock_business_repo.get_by_id.assert_called_once_with(business_id)
        mock_invoice_repo.list_by_business.assert_called_once_with(
            business_id=business_id, limit=50, offset=0
        )

    @pytest.mark.unit
    def test_list_invoices_business_not_found(
        self,
        invoice_service: InvoiceService,
        mock_business_repo: MagicMock,
    ) -> None:
        """Verify list_invoices raises BusinessNotFoundError if business does not exist."""
        business_id = uuid.uuid4()
        mock_business_repo.get_by_id.return_value = None

        with pytest.raises(BusinessNotFoundError, match=f"Business {business_id} not found"):
            invoice_service.list_invoices_by_business(business_id)

    @pytest.mark.unit
    def test_get_invoice_service_factory(self) -> None:
        """Verify get_invoice_service initializes InvoiceService with session dependencies."""
        mock_session = MagicMock()
        service = get_invoice_service(mock_session)
        assert isinstance(service, InvoiceService)
        assert service._session is mock_session
