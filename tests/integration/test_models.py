import concurrent.futures
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.models.business import Business
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice

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


class TestInvoiceAndBusinessPersistence:
    """Integration tests verifying persistence, Decimal typing, and database constraints."""

    @pytest.mark.integration
    def test_create_and_retrieve_business_and_invoice(self, db_session: Session) -> None:
        """Verify business and invoice creation, foreign key relation, and Decimal precision."""
        business = Business(
            tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
            legal_name="Acme Logistics LLC",
            status="ACTIVE",
        )
        db_session.add(business)
        db_session.flush()

        invoice_amount = Decimal("50000.00")
        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-2026-001",
            debtor_name="Global Freight Corp",
            amount=invoice_amount,
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status="SUBMITTED",
        )
        db_session.add(invoice)
        db_session.commit()

        # Query back and verify attributes
        retrieved = db_session.get(Invoice, invoice.id)
        assert retrieved is not None
        assert retrieved.invoice_number == "INV-2026-001"
        assert retrieved.debtor_name == "Global Freight Corp"
        assert retrieved.amount == Decimal("50000.00")
        assert isinstance(retrieved.amount, Decimal)
        assert retrieved.business.legal_name == "Acme Logistics LLC"

    @pytest.mark.integration
    def test_unique_constraint_duplicate_invoice_number(self, db_session: Session) -> None:
        """Verify database enforces UNIQUE(business_id, invoice_number)."""
        business = Business(
            tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
            legal_name="Duplicate Test Corp",
        )
        db_session.add(business)
        db_session.flush()

        inv1 = Invoice(
            business_id=business.id,
            invoice_number="DUP-001",
            debtor_name="Debtor A",
            amount=Decimal("1000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(inv1)
        db_session.flush()

        inv2 = Invoice(
            business_id=business.id,
            invoice_number="DUP-001",  # Same business, duplicate invoice number
            debtor_name="Debtor B",
            amount=Decimal("2000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(inv2)

        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.integration
    def test_check_constraint_amount_positive(self, db_session: Session) -> None:
        """Verify database enforces CHECK (amount > 0)."""
        business = Business(
            tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
            legal_name="Zero Amount Corp",
        )
        db_session.add(business)
        db_session.flush()

        inv = Invoice(
            business_id=business.id,
            invoice_number="ZERO-001",
            debtor_name="Debtor C",
            amount=Decimal("0.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(inv)

        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.integration
    def test_check_constraint_due_date_sequence(self, db_session: Session) -> None:
        """Verify database enforces CHECK (due_date >= issue_date)."""
        business = Business(
            tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
            legal_name="Invalid Dates Corp",
        )
        db_session.add(business)
        db_session.flush()

        inv = Invoice(
            business_id=business.id,
            invoice_number="DATE-001",
            debtor_name="Debtor D",
            amount=Decimal("1500.00"),
            issue_date=date(2026, 12, 1),
            due_date=date(2026, 11, 1),  # Due date before issue date
        )
        db_session.add(inv)

        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.integration
    def test_transaction_rollback_leaves_no_partial_records(self, db_session: Session) -> None:
        """Verify transaction rollback prevents orphaned or partially persisted records."""
        unique_tax_id = f"TAX-ROLLBACK-{uuid.uuid4().hex[:8]}"

        try:
            business = Business(
                tax_id=unique_tax_id,
                legal_name="Rollback Corp",
            )
            db_session.add(business)
            db_session.flush()

            # Add an invalid invoice to trigger constraint failure
            invalid_inv = Invoice(
                business_id=business.id,
                invoice_number="FAIL-001",
                debtor_name="Debtor E",
                amount=Decimal("-500.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )
            db_session.add(invalid_inv)
            db_session.flush()
        except IntegrityError:
            db_session.rollback()

        # Confirm the business was NOT committed
        retrieved_business = db_session.query(Business).filter_by(tax_id=unique_tax_id).first()
        assert retrieved_business is None

    @pytest.mark.integration
    def test_concurrent_duplicate_invoice_creation(self, db_engine: Engine) -> None:
        """Verify concurrent invoice creations with identical (business_id, invoice_number)

        result in exactly one commit success and concurrent collisions rejected by
        unique constraint violation.
        """
        with Session(bind=db_engine) as session:
            business = Business(
                tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
                legal_name="Concurrent Race Corp",
            )
            session.add(business)
            session.commit()
            business_id = business.id

        def attempt_insert() -> bool:
            with Session(bind=db_engine) as thread_session:
                try:
                    invoice = Invoice(
                        business_id=business_id,
                        invoice_number="CONCURRENT-INV-001",
                        debtor_name="Concurrent Debtor",
                        amount=Decimal("10000.00"),
                        issue_date=date(2026, 11, 1),
                        due_date=date(2026, 12, 1),
                    )
                    thread_session.add(invoice)
                    thread_session.commit()
                    return True
                except IntegrityError:
                    thread_session.rollback()
                    return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(attempt_insert) for _ in range(5)]
            results = [f.result() for f in futures]

        success_count = sum(1 for r in results if r is True)
        collision_count = sum(1 for r in results if r is False)

        assert success_count == 1
        assert collision_count == 4

    @pytest.mark.integration
    def test_cascade_delete_removes_associated_invoices(self, db_session: Session) -> None:
        """Verify deleting a Business cascades and removes associated Invoices."""
        business = Business(
            tax_id=f"TAX-{uuid.uuid4().hex[:8]}",
            legal_name="Cascade Parent Corp",
        )
        db_session.add(business)
        db_session.flush()

        invoice = Invoice(
            business_id=business.id,
            invoice_number="CASCADE-001",
            debtor_name="Debtor F",
            amount=Decimal("5000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(invoice)
        db_session.commit()

        invoice_id = invoice.id

        # Delete parent business
        db_session.delete(business)
        db_session.commit()

        # Both parent and child invoice must no longer exist
        assert db_session.get(Business, business.id) is None
        assert db_session.get(Invoice, invoice_id) is None

    @pytest.mark.integration
    def test_create_and_retrieve_financing_application(self, db_session: Session) -> None:
        """Verify persistence and relationships of FinancingApplication."""
        business = Business(
            tax_id=f"TAX-FIN-{uuid.uuid4().hex[:8]}",
            legal_name="Financed Business LLC",
        )
        db_session.add(business)
        db_session.flush()

        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-FIN-001",
            debtor_name="Debtor G",
            amount=Decimal("20000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(invoice)
        db_session.flush()

        app = FinancingApplication(
            business_id=business.id,
            invoice_id=invoice.id,
            requested_amount=Decimal("15000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.SUBMITTED,
        )
        db_session.add(app)
        db_session.commit()

        retrieved = db_session.get(FinancingApplication, app.id)
        assert retrieved is not None
        assert retrieved.business_id == business.id
        assert retrieved.invoice_id == invoice.id
        assert retrieved.requested_amount == Decimal("15000.00")
        assert retrieved.advance_rate == Decimal("0.8000")
        assert retrieved.fee_rate == Decimal("0.0300")
        assert retrieved.status == FinancingStatus.SUBMITTED
        assert retrieved.invoice.id == invoice.id
        assert retrieved.business.id == business.id
        assert len(invoice.financing_applications) == 1

    @pytest.mark.integration
    def test_financing_application_constraints_requested_amount_positive(
        self, db_session: Session
    ) -> None:
        """Verify DB check constraint prevents non-positive requested amounts."""
        business = Business(tax_id=f"TAX-{uuid.uuid4().hex[:8]}", legal_name="Corp")
        db_session.add(business)
        db_session.flush()

        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-CK-001",
            debtor_name="Debtor",
            amount=Decimal("1000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(invoice)
        db_session.flush()

        bad_app = FinancingApplication(
            business_id=business.id,
            invoice_id=invoice.id,
            requested_amount=Decimal("0.00"),
        )
        db_session.add(bad_app)
        with pytest.raises(IntegrityError, match="ck_financing_requested_amount_positive"):
            db_session.commit()
        db_session.rollback()

    @pytest.mark.integration
    def test_cascade_delete_removes_financing_applications(self, db_session: Session) -> None:
        """Verify deleting an invoice cascades to its financing applications."""
        business = Business(tax_id=f"TAX-{uuid.uuid4().hex[:8]}", legal_name="Corp")
        db_session.add(business)
        db_session.flush()

        invoice = Invoice(
            business_id=business.id,
            invoice_number="INV-CASC-001",
            debtor_name="Debtor",
            amount=Decimal("10000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(invoice)
        db_session.flush()

        app = FinancingApplication(
            business_id=business.id,
            invoice_id=invoice.id,
            requested_amount=Decimal("8000.00"),
        )
        db_session.add(app)
        db_session.commit()

        app_id = app.id
        db_session.delete(invoice)
        db_session.commit()

        assert db_session.get(FinancingApplication, app_id) is None
