import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.models.business import Business
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice
from financeflow.repositories.business import BusinessRepository
from financeflow.repositories.financing import FinancingRepository
from financeflow.repositories.invoice import InvoiceRepository

settings = get_settings()


@pytest.fixture(scope="module")
def db_engine():
    """Create a database engine connected to the PostgreSQL instance."""
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Provide a transactional database session per test with clean isolation."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


class TestBusinessRepository:
    """Integration tests for BusinessRepository against PostgreSQL."""

    @pytest.mark.integration
    def test_create_and_get_by_id(self, db_session: Session) -> None:
        """Verify creating a business and retrieving it by primary key ID."""
        repo = BusinessRepository(db_session)
        business = Business(
            tax_id=f"TAX-REPO-{uuid.uuid4().hex[:8]}",
            legal_name="Apex Logistics Corp",
            status="ACTIVE",
        )
        created = repo.create(business)
        db_session.flush()

        assert created.id is not None
        retrieved = repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.tax_id == created.tax_id
        assert retrieved.legal_name == "Apex Logistics Corp"

    @pytest.mark.integration
    def test_get_by_tax_id(self, db_session: Session) -> None:
        """Verify retrieving a business by its unique tax ID."""
        repo = BusinessRepository(db_session)
        tax_id = f"TAX-UNIQUE-{uuid.uuid4().hex[:8]}"
        business = Business(
            tax_id=tax_id,
            legal_name="Tax Lookup LLC",
            status="ACTIVE",
        )
        repo.create(business)
        db_session.flush()

        retrieved = repo.get_by_tax_id(tax_id)
        assert retrieved is not None
        assert retrieved.tax_id == tax_id
        assert retrieved.legal_name == "Tax Lookup LLC"

    @pytest.mark.integration
    def test_get_nonexistent_returns_none(self, db_session: Session) -> None:
        """Verify querying non-existent UUID or tax ID returns None."""
        repo = BusinessRepository(db_session)
        assert repo.get_by_id(uuid.uuid4()) is None
        assert repo.get_by_tax_id("NONEXISTENT-TAX-ID") is None

    @pytest.mark.integration
    def test_list_all_with_pagination(self, db_session: Session) -> None:
        """Verify listing businesses with pagination parameters."""
        repo = BusinessRepository(db_session)
        for i in range(3):
            repo.create(
                Business(
                    tax_id=f"TAX-PAGED-{i}-{uuid.uuid4().hex[:6]}",
                    legal_name=f"Paged Business {i}",
                )
            )
        db_session.flush()

        results_limit_2 = repo.list_all(limit=2, offset=0)
        assert len(results_limit_2) == 2

        results_offset_2 = repo.list_all(limit=2, offset=2)
        assert len(results_offset_2) >= 1


class TestInvoiceRepository:
    """Integration tests for InvoiceRepository against PostgreSQL."""

    @pytest.mark.integration
    def test_create_and_get_by_id(self, db_session: Session) -> None:
        """Verify creating an invoice and retrieving it with exact Decimal precision."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)

        business = b_repo.create(
            Business(
                tax_id=f"TAX-INV-{uuid.uuid4().hex[:8]}",
                legal_name="Invoice Issuer Inc",
            )
        )
        db_session.flush()

        amount = Decimal("12500.50")
        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-REPO-001",
            debtor_name="Mega Retailer Corp",
            amount=amount,
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status="SUBMITTED",
        )
        created = inv_repo.create(invoice)
        db_session.flush()

        retrieved = inv_repo.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.amount == Decimal("12500.50")
        assert isinstance(retrieved.amount, Decimal)
        assert retrieved.debtor_name == "Mega Retailer Corp"
        assert retrieved.invoice_number == "INV-REPO-001"

    @pytest.mark.integration
    def test_get_by_number(self, db_session: Session) -> None:
        """Verify retrieving an invoice by (business_id, invoice_number)."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)

        business = b_repo.create(
            Business(
                tax_id=f"TAX-NUM-{uuid.uuid4().hex[:8]}",
                legal_name="Number Lookup Corp",
            )
        )
        db_session.flush()

        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-TARGET-999",
            debtor_name="Target Debtor",
            amount=Decimal("4500.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        inv_repo.create(invoice)
        db_session.flush()

        retrieved = inv_repo.get_by_number(business.id, "INV-TARGET-999")
        assert retrieved is not None
        assert retrieved.id == invoice.id
        assert retrieved.invoice_number == "INV-TARGET-999"

        # Non-existent number returns None
        assert inv_repo.get_by_number(business.id, "NON-EXISTENT") is None

    @pytest.mark.integration
    def test_list_by_business_isolation_and_pagination(self, db_session: Session) -> None:
        """Verify listing invoices filters strictly by business_id and respects limit/offset."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)

        b1 = b_repo.create(
            Business(tax_id=f"TAX-B1-{uuid.uuid4().hex[:8]}", legal_name="Business One")
        )
        b2 = b_repo.create(
            Business(tax_id=f"TAX-B2-{uuid.uuid4().hex[:8]}", legal_name="Business Two")
        )
        db_session.flush()

        # Create 3 invoices for b1 and 1 for b2
        for i in range(3):
            inv_repo.create(
                Invoice(
                    business_id=b1.id,
                    invoice_number=f"INV-B1-{i}",
                    debtor_name="Debtor",
                    amount=Decimal("1000.00"),
                    issue_date=date(2026, 11, 1),
                    due_date=date(2026, 12, 1),
                )
            )
        inv_repo.create(
            Invoice(
                business_id=b2.id,
                invoice_number="INV-B2-0",
                debtor_name="Debtor",
                amount=Decimal("1000.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )
        )
        db_session.flush()

        b1_invoices = inv_repo.list_by_business(b1.id, limit=10, offset=0)
        assert len(b1_invoices) == 3
        for inv in b1_invoices:
            assert inv.business_id == b1.id

        b1_paged = inv_repo.list_by_business(b1.id, limit=2, offset=0)
        assert len(b1_paged) == 2

    @pytest.mark.integration
    def test_delete_invoice(self, db_session: Session) -> None:
        """Verify deleting an invoice through the repository."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)

        business = b_repo.create(
            Business(tax_id=f"TAX-DEL-{uuid.uuid4().hex[:8]}", legal_name="Del Corp")
        )
        db_session.flush()

        invoice = inv_repo.create(
            Invoice(
                business_id=business.id,
                invoice_number="INV-TO-DELETE",
                debtor_name="Debtor",
                amount=Decimal("3000.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )
        )
        db_session.flush()

        inv_id = invoice.id
        inv_repo.delete(invoice)
        db_session.flush()

        assert inv_repo.get_by_id(inv_id) is None


class TestFinancingRepository:
    """Integration tests for FinancingRepository executing queries against PostgreSQL."""

    @pytest.mark.integration
    def test_create_and_get_by_id(self, db_session: Session) -> None:
        """Verify creating and retrieving a FinancingApplication."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)
        fin_repo = FinancingRepository(db_session)

        business = b_repo.create(
            Business(tax_id=f"TAX-FREPO-{uuid.uuid4().hex[:8]}", legal_name="FinRepo Corp")
        )
        db_session.flush()

        invoice = inv_repo.create(
            Invoice(
                business_id=business.id,
                invoice_number="INV-FREPO-001",
                debtor_name="Debtor",
                amount=Decimal("10000.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )
        )
        db_session.flush()

        app = fin_repo.create(
            FinancingApplication(
                business_id=business.id,
                invoice_id=invoice.id,
                requested_amount=Decimal("8000.00"),
                advance_rate=Decimal("0.8000"),
                fee_rate=Decimal("0.0300"),
                status=FinancingStatus.SUBMITTED,
            )
        )
        db_session.flush()

        retrieved = fin_repo.get_by_id(app.id)
        assert retrieved is not None
        assert retrieved.id == app.id
        assert retrieved.requested_amount == Decimal("8000.00")
        assert retrieved.status == FinancingStatus.SUBMITTED

    @pytest.mark.integration
    def test_list_by_business_with_pagination(self, db_session: Session) -> None:
        """Verify listing applications by business with limit and offset."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)
        fin_repo = FinancingRepository(db_session)

        business = b_repo.create(
            Business(tax_id=f"TAX-FPAG-{uuid.uuid4().hex[:8]}", legal_name="Pag Corp")
        )
        db_session.flush()

        for i in range(3):
            inv = inv_repo.create(
                Invoice(
                    business_id=business.id,
                    invoice_number=f"INV-FPAG-{i}",
                    debtor_name="Debtor",
                    amount=Decimal("5000.00"),
                    issue_date=date(2026, 11, 1),
                    due_date=date(2026, 12, 1),
                )
            )
            db_session.flush()
            fin_repo.create(
                FinancingApplication(
                    business_id=business.id,
                    invoice_id=inv.id,
                    requested_amount=Decimal("4000.00"),
                )
            )
        db_session.flush()

        page1 = fin_repo.list_by_business(business.id, limit=2, offset=0)
        assert len(page1) == 2

        page2 = fin_repo.list_by_business(business.id, limit=2, offset=2)
        assert len(page2) == 1

    @pytest.mark.integration
    def test_get_active_by_invoice(self, db_session: Session) -> None:
        """Verify get_active_by_invoice finds active application and ignores rejected ones."""
        b_repo = BusinessRepository(db_session)
        inv_repo = InvoiceRepository(db_session)
        fin_repo = FinancingRepository(db_session)

        business = b_repo.create(
            Business(tax_id=f"TAX-ACT-{uuid.uuid4().hex[:8]}", legal_name="Act Corp")
        )
        db_session.flush()
        invoice = inv_repo.create(
            Invoice(
                business_id=business.id,
                invoice_number="INV-ACT-001",
                debtor_name="Debtor",
                amount=Decimal("12000.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )
        )
        db_session.flush()

        # Rejected application is not considered active
        fin_repo.create(
            FinancingApplication(
                business_id=business.id,
                invoice_id=invoice.id,
                requested_amount=Decimal("5000.00"),
                status=FinancingStatus.REJECTED,
            )
        )
        db_session.flush()
        assert fin_repo.get_active_by_invoice(invoice.id) is None

        # Submitted application is active
        submitted_app = fin_repo.create(
            FinancingApplication(
                business_id=business.id,
                invoice_id=invoice.id,
                requested_amount=Decimal("9000.00"),
                status=FinancingStatus.SUBMITTED,
            )
        )
        db_session.flush()
        active = fin_repo.get_active_by_invoice(invoice.id)
        assert active is not None
        assert active.id == submitted_app.id
