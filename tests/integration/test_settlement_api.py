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
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.models.settlement import Settlement

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
            tax_id=f"TAX-SETL-{uuid.uuid4().hex[:8]}",
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
            invoice_number=f"INV-SETL-{uuid.uuid4().hex[:8]}",
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
def disbursed_application(
    client: TestClient, active_business: uuid.UUID, submitted_invoice: uuid.UUID
) -> dict:
    """Create, approve, and disburse a financing application via API."""
    # 1. Create financing application: 80% on $50k -> $40k approved, $1,200 fee, $38,800 net
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
    app_id = create_resp.json()["id"]

    # 2. Approve application
    approve_resp = client.post(
        f"/api/v1/financing/{app_id}/approve",
        json={"reason": "Approved for full advance"},
    )
    assert approve_resp.status_code == 200

    # 3. Disburse application
    disb_resp = client.post(
        f"/api/v1/financing/{app_id}/disburse",
        json={
            "recipient_account": "ACC-WIRE-SETTLE-READY",
            "idempotency_key": f"idemp-disb-pre-{uuid.uuid4().hex}",
        },
    )
    assert disb_resp.status_code == 201

    get_app = client.get(f"/api/v1/financing/{app_id}")
    return get_app.json()


class TestSettlementIntegration:
    """PostgreSQL integration tests for debtor collection, reserve release, and ledger zeroing."""

    @pytest.mark.integration
    def test_full_lifecycle_settlement_and_ledger_zeroing(
        self,
        client: TestClient,
        db_engine,
        disbursed_application: dict,
    ) -> None:
        """Full lifecycle: Disbursed -> Debtor Pays $50k -> Cleared -> Reserve Released."""
        app_id = disbursed_application["id"]
        inv_id = disbursed_application["invoice_id"]
        idemp_key = f"idemp-settle-full-{uuid.uuid4().hex}"
        corr_id = f"corr-settle-{uuid.uuid4().hex}"

        # 1. Execute Settlement via API: Debtor pays $50,000.00, settlement fee $100.00
        settle_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "settlement_fee": "100.00",
                "idempotency_key": idemp_key,
                "correlation_id": corr_id,
            },
        )
        assert settle_resp.status_code == 200
        settle_data = settle_resp.json()
        assert settle_data["financing_application_id"] == app_id
        assert settle_data["status"] == "COMPLETED"
        assert settle_data["repayment_amount"] == "50000.00"
        assert settle_data["principal_repaid"] == "40000.00"
        assert settle_data["reserve_amount"] == "10000.00"
        assert settle_data["settlement_fee"] == "100.00"
        assert settle_data["net_reserve_refunded"] == "9900.00"
        s_id = settle_data["id"]

        # 2. Verify Database State
        with Session(bind=db_engine) as session:
            # Financing application is SETTLED
            app_entity = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_entity is not None
            assert app_entity.status == FinancingStatus.SETTLED.value

            # Underlying invoice is PAID
            inv_entity = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_entity is not None
            assert inv_entity.status == InvoiceStatus.PAID.value

            # Audit log written
            audit_stmt = (
                select(FinancingAuditLog)
                .where(FinancingAuditLog.application_id == uuid.UUID(app_id))
                .order_by(FinancingAuditLog.created_at.desc())
            )
            audit_entry = session.scalars(audit_stmt).first()
            assert audit_entry is not None
            assert audit_entry.from_status == FinancingStatus.DISBURSED.value
            assert audit_entry.to_status == FinancingStatus.SETTLED.value
            assert audit_entry.actor == "SETTLEMENT_SERVICE"
            assert audit_entry.correlation_id == corr_id

        # 3. Retrieve Settlement via GET endpoints
        get_by_app = client.get(f"/api/v1/financing/{app_id}/settlement")
        assert get_by_app.status_code == 200
        assert get_by_app.json()["id"] == s_id

        get_by_id = client.get(f"/api/v1/settlements/{s_id}")
        assert get_by_id.status_code == 200
        assert get_by_id.json()["idempotency_key"] == idemp_key

        # 4. Check Ledger Chart of Accounts API
        accounts_resp = client.get("/api/v1/ledger/accounts")
        assert accounts_resp.status_code == 200
        acc_dict = {a["account_number"]: a for a in accounts_resp.json()}

        # Receivables asset is extinguished (0.00 balance)
        assert acc_dict["1200"]["balance"] == "0.00"

        # Customer Reserve Payable liability is cleared (0.00 balance)
        assert acc_dict["2100"]["balance"] == "0.00"

        # Total fee revenue earned = $1,200 (disbursement) + $100 (settlement) = $1,300.00
        assert acc_dict["4010"]["balance"] == "1300.00"

        # Operating cash balance net inflow = -$38,800 + $50,000 - $9,900 = +$1,300.00
        assert acc_dict["1010"]["balance"] == "1300.00"

        # 5. Check Trial Balance Reconciliation API
        recon_resp = client.get("/api/v1/ledger/reconciliation")
        assert recon_resp.status_code == 200
        recon_data = recon_resp.json()
        assert recon_data["is_balanced"] is True
        assert recon_data["discrepancy"] == "0.00"

    @pytest.mark.integration
    def test_multiple_partial_collections_lifecycle_and_reconciliation(
        self,
        client: TestClient,
        db_engine,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Integration test for Fix 1 & 2: Multiple collections, deferred reserve, full zeroing."""
        # 1. Create and disburse application
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
        app_id = create_resp.json()["id"]

        approve_resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
        assert approve_resp.status_code == 200

        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-PARTIAL-DISB",
                "idempotency_key": f"idemp-disb-part-{uuid.uuid4().hex}",
            },
        )
        assert disb_resp.status_code == 201

        # 2. First partial payment: $30,000.00 of $50,000.00
        p1_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "30000.00",
                "settlement_fee": "0.00",
                "idempotency_key": f"idemp-p1-{uuid.uuid4().hex}",
            },
        )
        assert p1_resp.status_code == 200
        p1_data = p1_resp.json()
        assert p1_data["status"] == "SHORTFALL"
        assert p1_data["repayment_amount"] == "30000.00"
        assert p1_data["principal_repaid"] == "30000.00"
        assert p1_data["reserve_amount"] == "0.00"
        assert p1_data["net_reserve_refunded"] == "0.00"

        # Verify DB state after payment 1
        with Session(bind=db_engine) as session:
            app_e = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_e is not None
            assert app_e.status == FinancingStatus.PARTIALLY_SETTLED.value

            inv_e = session.get(Invoice, submitted_invoice)
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.FINANCED.value

        # Check ledger balances after payment 1: Reserve payable still intact ($10,000)
        acc_resp1 = client.get("/api/v1/ledger/accounts")
        assert acc_resp1.status_code == 200
        accs1 = {a["account_number"]: a for a in acc_resp1.json()}
        assert accs1["1200"]["balance"] == "20000.00"  # $50k - $30k = $20k outstanding
        assert accs1["2100"]["balance"] == "10000.00"  # Reserve liability remains intact

        # 3. Overpayment attempt: $25,000 when only $20,000 is outstanding
        overpay_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "25000.00",
                "idempotency_key": f"idemp-overpay-{uuid.uuid4().hex}",
            },
        )
        assert overpay_resp.status_code == 400
        assert "exceeds outstanding receivable" in overpay_resp.json()["detail"]

        # 4. Final partial payment: $20,000.00 with $100 fee completing obligation
        p2_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "20000.00",
                "settlement_fee": "100.00",
                "idempotency_key": f"idemp-p2-{uuid.uuid4().hex}",
            },
        )
        assert p2_resp.status_code == 200
        p2_data = p2_resp.json()
        assert p2_data["status"] == "COMPLETED"
        assert p2_data["repayment_amount"] == "20000.00"
        assert p2_data["principal_repaid"] == "10000.00"
        assert p2_data["reserve_amount"] == "10000.00"
        assert p2_data["settlement_fee"] == "100.00"
        assert p2_data["net_reserve_refunded"] == "9900.00"

        # Verify DB state after final payment
        with Session(bind=db_engine) as session:
            app_e = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_e is not None
            assert app_e.status == FinancingStatus.SETTLED.value

            inv_e = session.get(Invoice, submitted_invoice)
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.PAID.value

        # Check settlements list endpoint
        list_resp = client.get(f"/api/v1/financing/{app_id}/settlements")
        assert list_resp.status_code == 200
        settlements_list = list_resp.json()
        assert len(settlements_list) == 2
        assert settlements_list[0]["id"] == p1_data["id"]
        assert settlements_list[1]["id"] == p2_data["id"]

        # Check ledger balances after final payment: Zeroed!
        acc_resp2 = client.get("/api/v1/ledger/accounts")
        assert acc_resp2.status_code == 200
        accs2 = {a["account_number"]: a for a in acc_resp2.json()}
        assert accs2["1200"]["balance"] == "0.00"
        assert accs2["2100"]["balance"] == "0.00"

        # Trial balance reconciliation check
        rec_resp2 = client.get("/api/v1/ledger/reconciliation")
        assert rec_resp2.status_code == 200
        assert rec_resp2.json()["is_balanced"] is True
        assert rec_resp2.json()["discrepancy"] == "0.00"

    @pytest.mark.integration
    def test_idempotent_settlement_replay(
        self,
        client: TestClient,
        db_engine,
        disbursed_application: dict,
    ) -> None:
        """Sending identical idempotency key replays prior settlement without duplicate ledger."""
        app_id = disbursed_application["id"]
        idemp_key = f"idemp-settle-replay-{uuid.uuid4().hex}"

        # First settlement
        resp1 = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "idempotency_key": idemp_key,
            },
        )
        assert resp1.status_code == 200
        s1_id = resp1.json()["id"]

        # Second settlement with identical key
        resp2 = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "idempotency_key": idemp_key,
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["id"] == s1_id

        # Verify exactly 1 Settlement record in DB
        with Session(bind=db_engine) as session:
            stmt = select(Settlement).where(
                Settlement.financing_application_id == uuid.UUID(app_id)
            )
            records = list(session.scalars(stmt).all())
            assert len(records) == 1

    @pytest.mark.integration
    def test_duplicate_settlement_different_key_rejected_with_409(
        self,
        client: TestClient,
        disbursed_application: dict,
    ) -> None:
        """Attempting to settle an already settled application with a new key returns 409."""
        app_id = disbursed_application["id"]

        # First settlement
        resp1 = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "idempotency_key": f"idemp-first-{uuid.uuid4().hex}",
            },
        )
        assert resp1.status_code == 200

        # Second settlement with new key
        resp2 = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "idempotency_key": f"idemp-second-{uuid.uuid4().hex}",
            },
        )
        assert resp2.status_code == 409
        assert "already been settled" in resp2.json()["detail"]

    @pytest.mark.integration
    def test_settle_unapproved_or_undisbursed_application_returns_422(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Attempting to settle an application not in DISBURSED status returns 422."""
        # Create application (starts in SUBMITTED)
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

        # Attempt to settle directly
        settle_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "30000.00",
                "idempotency_key": f"idemp-early-{uuid.uuid4().hex}",
            },
        )
        assert settle_resp.status_code == 422
        assert "Cannot settle application in" in settle_resp.json()["detail"]

    @pytest.mark.integration
    def test_settle_nonexistent_application_returns_404(
        self,
        client: TestClient,
    ) -> None:
        """Attempting to settle a non-existent application returns 404."""
        random_id = uuid.uuid4()
        resp = client.post(
            f"/api/v1/financing/{random_id}/settle",
            json={
                "repayment_amount": "50000.00",
                "idempotency_key": f"idemp-none-{uuid.uuid4().hex}",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_concurrent_settlement_requests_prevent_race_condition(
        self,
        db_engine,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Concurrent settlement attempts: exactly 1 succeeds, others receive 409 Conflict."""
        # 1. Setup disbursed application
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
        app_id = create_resp.json()["id"]

        approve_resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
        assert approve_resp.status_code == 200

        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-CONC-DISB",
                "idempotency_key": f"idemp-conc-disb-{uuid.uuid4().hex}",
            },
        )
        assert disb_resp.status_code == 201

        # 2. Fire 5 concurrent settlement requests
        def call_settle(idx: int) -> int:
            with TestClient(app) as thread_client:
                r = thread_client.post(
                    f"/api/v1/financing/{app_id}/settle",
                    json={
                        "repayment_amount": "50000.00",
                        "idempotency_key": f"idemp-conc-settle-{idx}-{uuid.uuid4().hex}",
                    },
                )
                return r.status_code

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(call_settle, i) for i in range(5)]
            status_codes = [f.result() for f in as_completed(futures)]

        assert status_codes.count(200) == 1
        assert status_codes.count(409) == 4

        # Verify only 1 Settlement record in DB
        with Session(bind=db_engine) as session:
            stmt = select(Settlement).where(
                Settlement.financing_application_id == uuid.UUID(app_id)
            )
            records = list(session.scalars(stmt).all())
            assert len(records) == 1
