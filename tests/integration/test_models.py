import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.models.business import Business
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
