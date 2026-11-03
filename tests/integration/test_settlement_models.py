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
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.models.settlement import Settlement, SettlementStatus
from financeflow.repositories.settlement import SettlementRepository

settings = get_settings()


@pytest.fixture(scope="module")
def db_engine():
    """Create database engine connected to test PostgreSQL instance."""
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine):
    """Provide a transactional session per test with clean isolation."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def disbursed_application(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed business, invoice, and disbursed financing application for settlement testing."""
    business = Business(tax_id=f"TAX-SET-{uuid.uuid4().hex[:8]}", legal_name="Settlement Corp")
    db_session.add(business)
    db_session.flush()

    invoice = Invoice(
        business_id=business.id,
        invoice_number=f"INV-SET-{uuid.uuid4().hex[:8]}",
        debtor_name="MegaRetail Corp",
        amount=Decimal("50000.00"),
        currency="USD",
        issue_date=date(2026, 11, 1),
        due_date=date(2026, 12, 1),
        status=InvoiceStatus.FINANCED.value,
    )
    db_session.add(invoice)
    db_session.flush()

    application = FinancingApplication(
        business_id=business.id,
        invoice_id=invoice.id,
        requested_amount=Decimal("50000.00"),
        advance_rate=Decimal("0.8000"),
        fee_rate=Decimal("0.0300"),
        approved_amount=Decimal("40000.00"),
        fee_amount=Decimal("1200.00"),
        net_disbursement_amount=Decimal("38800.00"),
        status=FinancingStatus.DISBURSED.value,
    )
    db_session.add(application)
    db_session.commit()

    return application.id, invoice.id


class TestSettlementModelAndRepositoryIntegration:
    """Integration tests for Settlement entity and SettlementRepository."""

    @pytest.mark.integration
    def test_create_and_retrieve_settlement(
        self, db_session: Session, disbursed_application: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Verify settlement creation, foreign key relations, and repository lookup."""
        app_id, inv_id = disbursed_application
        repo = SettlementRepository(db_session)
        idemp_key = f"idemp-settle-{uuid.uuid4().hex}"

        settlement = Settlement(
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("100.00"),
            net_reserve_refunded=Decimal("9900.00"),
            status=SettlementStatus.COMPLETED.value,
            idempotency_key=idemp_key,
        )
        repo.create(settlement)
        db_session.commit()

        # Retrieve by ID
        found_by_id = repo.get_by_id(settlement.id)
        assert found_by_id is not None
        assert found_by_id.repayment_amount == Decimal("50000.00")
        assert found_by_id.principal_repaid == Decimal("40000.00")
        assert found_by_id.reserve_amount == Decimal("10000.00")
        assert found_by_id.settlement_fee == Decimal("100.00")
        assert found_by_id.net_reserve_refunded == Decimal("9900.00")
        assert found_by_id.status == SettlementStatus.COMPLETED.value

        # Retrieve by application ID
        found_by_app = repo.get_by_application_id(app_id)
        assert found_by_app is not None
        assert found_by_app.id == settlement.id

        # Retrieve by idempotency key
        found_by_key = repo.get_by_idempotency_key(idemp_key)
        assert found_by_key is not None
        assert found_by_key.id == settlement.id

    @pytest.mark.integration
    def test_settlement_unique_idempotency_key_constraint(
        self, db_session: Session, disbursed_application: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Verify database enforces unique idempotency_key on settlements."""
        app_id, inv_id = disbursed_application
        repo = SettlementRepository(db_session)
        shared_key = f"idemp-dup-{uuid.uuid4().hex}"

        s1 = Settlement(
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("10000.00"),
            status=SettlementStatus.COMPLETED.value,
            idempotency_key=shared_key,
        )
        repo.create(s1)
        db_session.commit()

        # Create another application for duplicate key test
        business2 = Business(
            tax_id=f"TAX-SET2-{uuid.uuid4().hex[:8]}", legal_name="Settlement Corp 2"
        )
        db_session.add(business2)
        db_session.flush()

        invoice2 = Invoice(
            business_id=business2.id,
            invoice_number=f"INV-SET2-{uuid.uuid4().hex[:8]}",
            debtor_name="Debtor 2",
            amount=Decimal("20000.00"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.FINANCED.value,
        )
        db_session.add(invoice2)
        db_session.flush()

        app2 = FinancingApplication(
            business_id=business2.id,
            invoice_id=invoice2.id,
            requested_amount=Decimal("16000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            status=FinancingStatus.DISBURSED.value,
        )
        db_session.add(app2)
        db_session.commit()

        # S2 with duplicate key
        s2 = Settlement(
            financing_application_id=app2.id,
            invoice_id=invoice2.id,
            repayment_amount=Decimal("20000.00"),
            principal_repaid=Decimal("16000.00"),
            reserve_amount=Decimal("4000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("4000.00"),
            status=SettlementStatus.COMPLETED.value,
            idempotency_key=shared_key,
        )
        with pytest.raises(IntegrityError, match="ix_settlements_idempotency_key"):
            repo.create(s2)
        db_session.rollback()

    @pytest.mark.integration
    def test_multiple_settlements_allowed_for_application(
        self, db_session: Session, disbursed_application: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Verify multiple collection records can exist for the same financing application."""
        app_id, inv_id = disbursed_application
        repo = SettlementRepository(db_session)

        s1 = Settlement(
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("30000.00"),
            principal_repaid=Decimal("24000.00"),
            reserve_amount=Decimal("6000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("0.00"),
            status=SettlementStatus.SHORTFALL.value,
            idempotency_key=f"idemp-s1-{uuid.uuid4().hex}",
        )
        repo.create(s1)
        db_session.commit()

        s2 = Settlement(
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("20000.00"),
            principal_repaid=Decimal("16000.00"),
            reserve_amount=Decimal("4000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("10000.00"),
            status=SettlementStatus.COMPLETED.value,
            idempotency_key=f"idemp-s2-{uuid.uuid4().hex}",
        )
        repo.create(s2)
        db_session.commit()

        settlements = repo.list_by_application_id(app_id)
        assert len(settlements) == 2
        assert settlements[0].id == s1.id
        assert settlements[1].id == s2.id
