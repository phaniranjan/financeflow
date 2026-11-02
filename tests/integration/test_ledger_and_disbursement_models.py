import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.business import Business
from financeflow.models.disbursement import Disbursement
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice
from financeflow.models.ledger import (
    AccountType,
    EntryType,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from financeflow.repositories.audit import AuditRepository
from financeflow.repositories.disbursement import DisbursementRepository
from financeflow.repositories.ledger import LedgerRepository

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
def db_session(db_engine: Engine):
    """Provide a transactional database session per test with clean isolation."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def seeded_financing_application(db_session: Session) -> uuid.UUID:
    """Seed business, invoice, and approved financing application for disbursement tests."""
    business = Business(tax_id=f"TAX-LDG-{uuid.uuid4().hex[:8]}", legal_name="Ledger Corp")
    db_session.add(business)
    db_session.flush()

    invoice = Invoice(
        business_id=business.id,
        invoice_number=f"INV-LDG-{uuid.uuid4().hex[:6]}",
        debtor_name="Debtor Corp",
        amount=Decimal("50000.00"),
        issue_date=date(2026, 11, 1),
        due_date=date(2026, 12, 1),
    )
    db_session.add(invoice)
    db_session.flush()

    app = FinancingApplication(
        business_id=business.id,
        invoice_id=invoice.id,
        requested_amount=Decimal("40000.00"),
        approved_amount=Decimal("32000.00"),
        advance_rate=Decimal("0.8000"),
        fee_rate=Decimal("0.0300"),
        fee_amount=Decimal("960.00"),
        net_disbursement_amount=Decimal("31040.00"),
        status=FinancingStatus.APPROVED.value,
    )
    db_session.add(app)
    db_session.commit()
    return app.id


class TestLedgerPersistenceAndBalanceCalculation:
    """Integration tests verifying double-entry ledger models and balance calculations."""

    @pytest.mark.integration
    def test_create_and_retrieve_ledger_account(self, db_session: Session) -> None:
        """Verify creating chart of accounts entities and retrieving by code and ID."""
        repo = LedgerRepository(db_session)
        account = LedgerAccount(
            account_number="1010",
            name="Operating Cash",
            account_type=AccountType.ASSET.value,
            currency="USD",
        )
        repo.create_account(account)
        db_session.commit()

        retrieved = repo.get_account_by_number("1010")
        assert retrieved is not None
        assert retrieved.name == "Operating Cash"
        assert retrieved.account_type == AccountType.ASSET.value

        retrieved_by_id = repo.get_account_by_id(account.id)
        assert retrieved_by_id is not None
        assert retrieved_by_id.account_number == "1010"

    @pytest.mark.integration
    def test_create_balanced_ledger_transaction_and_entries(self, db_session: Session) -> None:
        """Verify posting balanced double-entry transaction (Debits == Credits)."""
        repo = LedgerRepository(db_session)

        # 1. Create accounts: Cash (Asset), Factoring Receivable (Asset), Fee Revenue (Revenue)
        cash_acc = repo.create_account(
            LedgerAccount(
                account_number=f"1010-{uuid.uuid4().hex[:4]}",
                name="Operating Cash",
                account_type=AccountType.ASSET.value,
            )
        )
        rec_acc = repo.create_account(
            LedgerAccount(
                account_number=f"1200-{uuid.uuid4().hex[:4]}",
                name="Factoring Receivables",
                account_type=AccountType.ASSET.value,
            )
        )
        rev_acc = repo.create_account(
            LedgerAccount(
                account_number=f"4010-{uuid.uuid4().hex[:4]}",
                name="Financing Fee Revenue",
                account_type=AccountType.REVENUE.value,
            )
        )
        db_session.flush()

        # 2. Post Disbursement Transaction:
        # Debit: Factoring Receivables (Asset) +$32,000.00
        # Credit: Fee Revenue (Revenue) +$960.00
        # Credit: Operating Cash (Asset) -$31,040.00
        ref_id = uuid.uuid4()
        tx = repo.create_transaction(
            LedgerTransaction(
                transaction_type="FINANCING_DISBURSEMENT",
                reference_id=ref_id,
                description="Disbursement for application",
            )
        )
        db_session.flush()

        e1 = repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=rec_acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=Decimal("32000.00"),
            )
        )
        e2 = repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=rev_acc.id,
                entry_type=EntryType.CREDIT.value,
                amount=Decimal("960.00"),
            )
        )
        e3 = repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=cash_acc.id,
                entry_type=EntryType.CREDIT.value,
                amount=Decimal("31040.00"),
            )
        )
        db_session.commit()

        # 3. Verify retrieved transaction and relationships
        retrieved_tx = repo.get_transaction_by_reference(ref_id)
        assert retrieved_tx is not None
        assert len(retrieved_tx.entries) == 3

        # 4. Verify balances
        # Receivables (Asset): +$32,000.00
        assert repo.get_account_balance(rec_acc.id) == Decimal("32000.00")
        # Fee Revenue (Revenue): +$960.00
        assert repo.get_account_balance(rev_acc.id) == Decimal("960.00")
        # Cash (Asset): -$31,040.00
        assert repo.get_account_balance(cash_acc.id) == Decimal("-31040.00")

        # 5. Verify total debits == total credits across the transaction
        entries = [e1, e2, e3]
        debits = sum(e.amount for e in entries if e.entry_type == EntryType.DEBIT.value)
        credits = sum(e.amount for e in entries if e.entry_type == EntryType.CREDIT.value)
        assert debits == Decimal("32000.00")
        assert credits == Decimal("32000.00")
        assert debits == credits

    @pytest.mark.integration
    def test_ledger_entry_amount_positive_constraint(self, db_session: Session) -> None:
        """Verify DB check constraint prevents non-positive ledger entry amounts."""
        repo = LedgerRepository(db_session)
        acc = repo.create_account(
            LedgerAccount(
                account_number=f"TEST-{uuid.uuid4().hex[:6]}",
                name="Test Account",
                account_type=AccountType.ASSET.value,
            )
        )
        tx = repo.create_transaction(
            LedgerTransaction(
                transaction_type="TEST",
                reference_id=uuid.uuid4(),
                description="Test",
            )
        )
        db_session.flush()

        bad_entry = LedgerEntry(
            transaction_id=tx.id,
            account_id=acc.id,
            entry_type=EntryType.DEBIT.value,
            amount=Decimal("0.00"),
        )
        db_session.add(bad_entry)
        with pytest.raises(IntegrityError, match="ck_ledger_entry_amount_positive"):
            db_session.commit()
        db_session.rollback()

    @pytest.mark.integration
    def test_restrict_delete_prevents_removing_account_with_entries(
        self, db_session: Session
    ) -> None:
        """Verify DB foreign key RESTRICT prevents deleting account that has entries."""
        repo = LedgerRepository(db_session)
        acc = repo.create_account(
            LedgerAccount(
                account_number=f"NO-DEL-{uuid.uuid4().hex[:4]}",
                name="Permanent Account",
                account_type=AccountType.ASSET.value,
            )
        )
        tx = repo.create_transaction(
            LedgerTransaction(
                transaction_type="TEST",
                reference_id=uuid.uuid4(),
                description="Test",
            )
        )
        db_session.flush()

        repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=Decimal("100.00"),
            )
        )
        db_session.commit()

        db_session.delete(acc)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    @pytest.mark.integration
    def test_get_transaction_by_id_and_entries_for_account(self, db_session: Session) -> None:
        """Verify get_transaction_by_id and get_entries_for_account."""
        repo = LedgerRepository(db_session)
        acc = repo.create_account(
            LedgerAccount(
                account_number=f"7{uuid.uuid4().hex[:3]}",
                name="Temp Account",
                account_type=AccountType.EXPENSE.value,
            )
        )
        tx = repo.create_transaction(
            LedgerTransaction(
                transaction_type="LOOKUP_TEST",
                reference_id=uuid.uuid4(),
                description="Lookup test",
            )
        )
        entry = repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=Decimal("250.00"),
            )
        )
        db_session.commit()

        retrieved_tx = repo.get_transaction_by_id(tx.id)
        assert retrieved_tx is not None
        assert retrieved_tx.id == tx.id

        entries = repo.get_entries_for_account(acc.id)
        assert len(entries) == 1
        assert entries[0].id == entry.id
        assert entries[0].amount == Decimal("250.00")

    @pytest.mark.integration
    def test_get_account_balance_nonexistent_returns_zero(self, db_session: Session) -> None:
        """Verify get_account_balance returns Decimal 0.00 for unknown account UUID."""
        repo = LedgerRepository(db_session)
        balance = repo.get_account_balance(uuid.uuid4())
        assert balance == Decimal("0.00")


class TestDisbursementPersistenceAndConstraints:
    """Integration tests for Disbursement entities, idempotency, and uniqueness."""

    @pytest.mark.integration
    def test_create_and_retrieve_disbursement(
        self, db_session: Session, seeded_financing_application: uuid.UUID
    ) -> None:
        """Verify creating disbursement and querying by ID, application_id, and idempotency_key."""
        repo = DisbursementRepository(db_session)
        idemp_key = f"idemp-test-{uuid.uuid4().hex[:8]}"

        disbursement = Disbursement(
            financing_application_id=seeded_financing_application,
            idempotency_key=idemp_key,
            amount=Decimal("31040.00"),
            recipient_account="ACC-998877",
            status="COMPLETED",
            provider_transaction_id="sim_tx_123456",
        )
        repo.create(disbursement)
        db_session.commit()

        retrieved = repo.get_by_id(disbursement.id)
        assert retrieved is not None
        assert retrieved.amount == Decimal("31040.00")
        assert retrieved.status == "COMPLETED"
        assert retrieved.recipient_account == "ACC-998877"

        by_app = repo.get_by_application_id(seeded_financing_application)
        assert by_app is not None
        assert by_app.id == disbursement.id

        by_key = repo.get_by_idempotency_key(idemp_key)
        assert by_key is not None
        assert by_key.id == disbursement.id

    @pytest.mark.integration
    def test_disbursement_idempotency_key_unique_constraint(self, db_session: Session) -> None:
        """Verify database enforces unique idempotency_key across disbursements."""
        repo = DisbursementRepository(db_session)
        shared_key = f"idemp-dup-{uuid.uuid4().hex[:8]}"

        # Seed two different financing applications
        b = Business(tax_id=f"TAX-IDM-{uuid.uuid4().hex[:6]}", legal_name="Idemp Corp")
        db_session.add(b)
        db_session.flush()

        inv = Invoice(
            business_id=b.id,
            invoice_number=f"INV-IDM-{uuid.uuid4().hex[:4]}",
            debtor_name="Debtor",
            amount=Decimal("20000.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        db_session.add(inv)
        db_session.flush()

        app1 = FinancingApplication(
            business_id=b.id,
            invoice_id=inv.id,
            requested_amount=Decimal("10000.00"),
        )
        app2 = FinancingApplication(
            business_id=b.id,
            invoice_id=inv.id,
            requested_amount=Decimal("5000.00"),
            status=FinancingStatus.REJECTED.value,  # not active
        )
        db_session.add_all([app1, app2])
        db_session.commit()

        d1 = Disbursement(
            financing_application_id=app1.id,
            idempotency_key=shared_key,
            amount=Decimal("8000.00"),
            recipient_account="ACC-1",
            status="COMPLETED",
        )
        repo.create(d1)
        db_session.commit()

        d2 = Disbursement(
            financing_application_id=app2.id,
            idempotency_key=shared_key,
            amount=Decimal("4000.00"),
            recipient_account="ACC-2",
            status="COMPLETED",
        )
        with pytest.raises(IntegrityError, match="ix_disbursements_idempotency_key"):
            repo.create(d2)
        db_session.rollback()

    @pytest.mark.integration
    def test_disbursement_single_per_application_unique_constraint(
        self, db_session: Session, seeded_financing_application: uuid.UUID
    ) -> None:
        """Verify database prevents creating multiple disbursements for the same application."""
        repo = DisbursementRepository(db_session)

        d1 = Disbursement(
            financing_application_id=seeded_financing_application,
            idempotency_key=f"idemp-app-1-{uuid.uuid4().hex[:6]}",
            amount=Decimal("10000.00"),
            recipient_account="ACC-1",
            status="COMPLETED",
        )
        repo.create(d1)
        db_session.commit()

        d2 = Disbursement(
            financing_application_id=seeded_financing_application,
            idempotency_key=f"idemp-app-2-{uuid.uuid4().hex[:6]}",
            amount=Decimal("10000.00"),
            recipient_account="ACC-1",
            status="COMPLETED",
        )
        with pytest.raises(IntegrityError, match="ix_disbursements_financing_application_id"):
            repo.create(d2)
        db_session.rollback()


class TestFinancingAuditLogPersistence:
    """Integration tests for FinancingAuditLog entity and AuditRepository."""

    @pytest.mark.integration
    def test_audit_log_creation_and_chronological_retrieval(
        self, db_session: Session, seeded_financing_application: uuid.UUID
    ) -> None:
        """Verify audit events are recorded with correlation IDs and retrieved chronologically."""
        repo = AuditRepository(db_session)
        corr_id = str(uuid.uuid4())

        log1 = FinancingAuditLog(
            application_id=seeded_financing_application,
            from_status=FinancingStatus.SUBMITTED.value,
            to_status=FinancingStatus.APPROVED.value,
            actor="SYSTEM_AUTO_UNDERWRITING",
            correlation_id=corr_id,
            reason="Approved per credit policy 2026.1",
        )
        repo.create(log1)

        log2 = FinancingAuditLog(
            application_id=seeded_financing_application,
            from_status=FinancingStatus.APPROVED.value,
            to_status=FinancingStatus.DISBURSED.value,
            actor="PAYMENT_GATEWAY",
            correlation_id=corr_id,
            reason="Disbursement executed successfully",
        )
        repo.create(log2)
        db_session.commit()

        logs = repo.list_by_application(seeded_financing_application)
        assert len(logs) == 2
        assert logs[0].to_status == FinancingStatus.APPROVED.value
        assert logs[1].to_status == FinancingStatus.DISBURSED.value
        assert logs[0].correlation_id == corr_id
