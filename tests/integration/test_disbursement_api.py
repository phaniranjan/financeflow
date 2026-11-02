import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.main import app
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.business import Business, BusinessStatus
from financeflow.models.disbursement import Disbursement
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.models.ledger import (
    EntryType,
    LedgerEntry,
    LedgerTransaction,
)

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
def client(db_engine) -> TestClient:
    """Provide a FastAPI TestClient configured for the test database."""
    assert db_engine is not None
    return TestClient(app)


@pytest.fixture
def active_business(db_engine) -> uuid.UUID:
    """Seed an active business for testing."""
    with Session(bind=db_engine) as session:
        business = Business(
            tax_id=f"TAX-DISB-{uuid.uuid4().hex[:8]}",
            legal_name="Apex Global Trade LLC",
            status=BusinessStatus.ACTIVE.value,
        )
        session.add(business)
        session.commit()
        session.refresh(business)
        b_id = business.id
    return b_id


@pytest.fixture
def submitted_invoice(db_engine, active_business: uuid.UUID) -> uuid.UUID:
    """Seed an eligible submitted invoice."""
    with Session(bind=db_engine) as session:
        invoice = Invoice(
            business_id=active_business,
            invoice_number=f"INV-DISB-{uuid.uuid4().hex[:8]}",
            debtor_name="MegaCorp Logistics",
            amount=Decimal("50000.00"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.SUBMITTED.value,
        )
        session.add(invoice)
        session.commit()
        session.refresh(invoice)
        inv_id = invoice.id
    return inv_id


@pytest.fixture
def approved_application(
    client: TestClient, active_business: uuid.UUID, submitted_invoice: uuid.UUID
) -> dict:
    """Create and approve a financing application through the REST API."""
    # 1. Create: 80% advance on $50k -> $40k approved, 3% fee -> $1,200, net $38,800
    create_resp = client.post(
        "/api/v1/financing",
        json={
            "business_id": str(active_business),
            "invoice_id": str(submitted_invoice),
            "requested_amount": "50000.00",
            "advance_rate": "0.8000",
            "fee_rate": "0.0300",
        },
    )
    assert create_resp.status_code == 201
    app_data = create_resp.json()
    app_id = app_data["id"]

    # 2. Approve application
    approve_resp = client.post(
        f"/api/v1/financing/{app_id}/approve",
        json={"reason": "Approved for full advance"},
    )
    assert approve_resp.status_code == 200
    return approve_resp.json()


class TestDisbursementIntegration:
    """PostgreSQL integration tests for disbursement payout, ledger posting, and reconciliation."""

    @pytest.mark.integration
    def test_end_to_end_disbursement_and_ledger_reconciliation(
        self,
        client: TestClient,
        db_engine,
        approved_application: dict,
    ) -> None:
        """Verify full lifecycle: Approved Financing -> Disburse -> Ledger Updated -> Reconciled."""
        app_id = approved_application["id"]
        inv_id = approved_application["invoice_id"]
        idemp_key = f"idemp-{uuid.uuid4().hex}"
        corr_id = f"corr-{uuid.uuid4().hex}"

        # 1. Execute Disbursement via API
        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-889900",
                "idempotency_key": idemp_key,
                "correlation_id": corr_id,
            },
        )
        assert disb_resp.status_code == 201
        disb_data = disb_resp.json()
        assert disb_data["financing_application_id"] == app_id
        assert disb_data["amount"] == "38800.00"
        assert disb_data["recipient_account"] == "ACC-WIRE-889900"
        assert disb_data["status"] == "COMPLETED"
        assert disb_data["provider_transaction_id"] is not None
        disb_id = disb_data["id"]

        # 2. Verify Database State
        with Session(bind=db_engine) as session:
            # Check Financing Application status
            app_entity = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_entity is not None
            assert app_entity.status == FinancingStatus.DISBURSED.value

            # Check Invoice status
            inv_entity = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_entity is not None
            assert inv_entity.status == InvoiceStatus.FINANCED.value

            # Check Audit Log
            stmt = (
                select(FinancingAuditLog)
                .where(FinancingAuditLog.application_id == uuid.UUID(app_id))
                .order_by(FinancingAuditLog.created_at.desc())
            )
            audit_entry = session.scalars(stmt).first()
            assert audit_entry is not None
            assert audit_entry.from_status == FinancingStatus.APPROVED.value
            assert audit_entry.to_status == FinancingStatus.DISBURSED.value
            assert audit_entry.actor == "DISBURSEMENT_SERVICE"
            assert audit_entry.correlation_id == corr_id

            # Check Double-entry Ledger Transaction
            tx_stmt = select(LedgerTransaction).where(
                LedgerTransaction.reference_id == uuid.UUID(app_id)
            )
            tx = session.scalars(tx_stmt).first()
            assert tx is not None
            assert tx.transaction_type == "FINANCING_DISBURSEMENT"

            entries_stmt = select(LedgerEntry).where(LedgerEntry.transaction_id == tx.id)
            entries = list(session.scalars(entries_stmt).all())
            assert len(entries) == 3

            # Verify debits == credits
            total_debits = sum(
                (e.amount for e in entries if e.entry_type == EntryType.DEBIT.value),
                Decimal("0.00"),
            )
            total_credits = sum(
                (e.amount for e in entries if e.entry_type == EntryType.CREDIT.value),
                Decimal("0.00"),
            )
            assert total_debits == Decimal("40000.00")
            assert total_credits == Decimal("40000.00")
            assert total_debits == total_credits

        # 3. Retrieve Disbursement by Application ID
        get_app_disb = client.get(f"/api/v1/financing/{app_id}/disbursement")
        assert get_app_disb.status_code == 200
        assert get_app_disb.json()["id"] == disb_id

        # 4. Retrieve Disbursement by Disbursement ID
        get_disb = client.get(f"/api/v1/disbursements/{disb_id}")
        assert get_disb.status_code == 200
        assert get_disb.json()["idempotency_key"] == idemp_key

        # 5. Check Ledger Chart of Accounts API
        accounts_resp = client.get("/api/v1/ledger/accounts")
        assert accounts_resp.status_code == 200
        accounts_data = accounts_resp.json()
        assert len(accounts_data) >= 4
        acc_dict = {a["account_number"]: a for a in accounts_data}
        assert acc_dict["1200"]["balance"] == "40000.00"  # Receivables asset debit balance
        assert acc_dict["4010"]["balance"] == "1200.00"  # Fee revenue credit balance
        assert acc_dict["1010"]["balance"] == "-38800.00"  # Cash asset credit reduction

        # 6. Check Ledger Trial Balance Reconciliation API
        recon_resp = client.get("/api/v1/ledger/reconciliation")
        assert recon_resp.status_code == 200
        recon_data = recon_resp.json()
        assert recon_data["is_balanced"] is True
        assert recon_data["discrepancy"] == "0.00"

    @pytest.mark.integration
    def test_idempotent_disbursement_replay(
        self,
        client: TestClient,
        db_engine,
        approved_application: dict,
    ) -> None:
        """Sending identical idempotency key replays prior disbursement without duplicate payout."""
        app_id = approved_application["id"]
        idemp_key = f"idemp-replay-{uuid.uuid4().hex}"

        # First request
        resp1 = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-112233",
                "idempotency_key": idemp_key,
            },
        )
        assert resp1.status_code == 201
        disb1_id = resp1.json()["id"]

        # Second request with identical idempotency key
        resp2 = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-112233",
                "idempotency_key": idemp_key,
            },
        )
        # Should succeed and return the existing record
        assert resp2.status_code == 201
        assert resp2.json()["id"] == disb1_id

        # Verify database has exactly 1 disbursement for this application
        with Session(bind=db_engine) as session:
            stmt = select(Disbursement).where(
                Disbursement.financing_application_id == uuid.UUID(app_id)
            )
            disbursements = list(session.scalars(stmt).all())
            assert len(disbursements) == 1

    @pytest.mark.integration
    def test_duplicate_disbursement_different_key_rejected_with_409(
        self,
        client: TestClient,
        approved_application: dict,
    ) -> None:
        """Disbursing an already disbursed application with a new key returns 409 Conflict."""
        app_id = approved_application["id"]

        # First disbursement succeeds
        resp1 = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-FIRST",
                "idempotency_key": f"idemp-first-{uuid.uuid4().hex}",
            },
        )
        assert resp1.status_code == 201

        # Second disbursement with different key
        resp2 = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-SECOND",
                "idempotency_key": f"idemp-second-{uuid.uuid4().hex}",
            },
        )
        assert resp2.status_code == 409
        assert "already been disbursed" in resp2.json()["detail"]

    @pytest.mark.integration
    def test_disburse_unapproved_application_returns_422(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Attempting to disburse an application that is not in APPROVED status returns 422."""
        # Create application (starts in DRAFT or SUBMITTED)
        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "30000.00",
                "advance_rate": "0.8000",
                "fee_rate": "0.0300",
            },
        )
        assert create_resp.status_code == 201
        app_id = create_resp.json()["id"]

        # Attempt disbursement directly without approval
        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-EARLY",
                "idempotency_key": f"idemp-early-{uuid.uuid4().hex}",
            },
        )
        assert disb_resp.status_code == 422
        assert "Cannot disburse application in" in disb_resp.json()["detail"]

    @pytest.mark.integration
    def test_disburse_nonexistent_application_returns_404(
        self,
        client: TestClient,
    ) -> None:
        """Attempting to disburse a non-existent application returns 404."""
        random_id = uuid.uuid4()
        resp = client.post(
            f"/api/v1/financing/{random_id}/disburse",
            json={
                "recipient_account": "ACC-WIRE-NONE",
                "idempotency_key": f"idemp-none-{uuid.uuid4().hex}",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_concurrent_disbursement_requests_prevent_race_condition(
        self,
        db_engine,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Concurrent disburse requests on same application: exactly 1 succeeds, others 409."""
        # 1. Setup approved application
        with TestClient(app) as test_client:
            create_resp = test_client.post(
                "/api/v1/financing",
                json={
                    "business_id": str(active_business),
                    "invoice_id": str(submitted_invoice),
                    "requested_amount": "40000.00",
                    "advance_rate": "0.8000",
                    "fee_rate": "0.0300",
                },
            )
            assert create_resp.status_code == 201
            app_id = create_resp.json()["id"]

            approve_resp = test_client.post(
                f"/api/v1/financing/{app_id}/approve",
                json={"reason": "Concurrency test approval"},
            )
            assert approve_resp.status_code == 200

        # 2. Fire 5 concurrent requests with distinct idempotency keys
        def call_disburse(idx: int) -> int:
            with TestClient(app) as thread_client:
                r = thread_client.post(
                    f"/api/v1/financing/{app_id}/disburse",
                    json={
                        "recipient_account": f"ACC-CONCURRENT-{idx}",
                        "idempotency_key": f"idemp-conc-{idx}-{uuid.uuid4().hex}",
                    },
                )
                return r.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(call_disburse, i) for i in range(5)]
            status_codes = [f.result() for f in as_completed(futures)]

        # Exactly one thread succeeded (201), the rest got 409 Conflict
        assert status_codes.count(201) == 1
        assert status_codes.count(409) == 4

        # Verify only 1 Disbursement record exists in DB
        with Session(bind=db_engine) as session:
            stmt = select(Disbursement).where(
                Disbursement.financing_application_id == uuid.UUID(app_id)
            )
            records = list(session.scalars(stmt).all())
            assert len(records) == 1

            # Verify exactly 1 ledger transaction was posted
            tx_stmt = select(LedgerTransaction).where(
                LedgerTransaction.reference_id == uuid.UUID(app_id)
            )
            txs = list(session.scalars(tx_stmt).all())
            assert len(txs) == 1
