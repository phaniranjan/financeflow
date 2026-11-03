"""End-to-End Business Workflow Acceptance Test (Cycle 7.2).

Demonstrates the complete invoice factoring lifecycle against real PostgreSQL:
Invoice Issuance -> Financing Application -> Risk Approval -> Idempotent Disbursement
-> Multiple Partial Debtor Collections -> Final Settlement -> Contractual Reserve Release
-> Complete Ledger Balance Zeroing & Financial Reconciliation.
"""

import uuid

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
from financeflow.models.settlement import Settlement, SettlementStatus

settings = get_settings()


@pytest.fixture(scope="module")
def db_engine():
    """Create a database engine connected to PostgreSQL and initialize schema."""
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(db_engine) -> TestClient:
    """Provide a FastAPI TestClient configured for PostgreSQL."""
    assert db_engine is not None
    return TestClient(app)


class TestEndToEndFactoringLifecycle:
    """Comprehensive macro-integration test exercising the complete financial workflow."""

    @pytest.mark.integration
    def test_complete_factoring_lifecycle_and_ledger_zeroing(
        self,
        client: TestClient,
        db_engine,
    ) -> None:
        """Execute and verify every phase of the invoice factoring lifecycle."""
        # ---------------------------------------------------------------------
        # Phase 1: Business Registration & Invoice Issuance ($50,000.00)
        # ---------------------------------------------------------------------
        with Session(bind=db_engine) as session:
            supplier = Business(
                tax_id=f"TAX-E2E-{uuid.uuid4().hex[:8]}",
                legal_name="Starlight Logistics Global Inc",
                status=BusinessStatus.ACTIVE.value,
            )
            session.add(supplier)
            session.commit()
            supplier_id = supplier.id

        inv_number = f"INV-E2E-{uuid.uuid4().hex[:8]}"
        inv_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(supplier_id),
                "invoice_number": inv_number,
                "debtor_name": "Enterprise Retailers Corp",
                "amount": "50000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
        )
        assert inv_resp.status_code == 201
        inv_id = inv_resp.json()["id"]
        assert inv_resp.json()["status"] == InvoiceStatus.SUBMITTED.value
        assert inv_resp.json()["amount"] == "50000.00"

        # ---------------------------------------------------------------------
        # Phase 2: Financing Application Submission ($50,000 Collateral Pledged)
        # ---------------------------------------------------------------------
        fin_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(supplier_id),
                "invoice_id": inv_id,
                "requested_amount": "50000.00",
                "advance_rate": "0.8000",
                "fee_rate": "0.0300",
            },
        )
        assert fin_resp.status_code == 201
        app_id = fin_resp.json()["id"]
        assert fin_resp.json()["status"] == FinancingStatus.SUBMITTED.value

        # ---------------------------------------------------------------------
        # Phase 3: Risk Assessment & Underwriting Approval
        # ---------------------------------------------------------------------
        appr_resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
        assert appr_resp.status_code == 200
        appr_data = appr_resp.json()
        assert appr_data["status"] == FinancingStatus.APPROVED.value
        assert appr_data["approved_amount"] == "40000.00"  # 80% of $50k
        assert appr_data["fee_amount"] == "1200.00"  # 3% of $40k
        assert appr_data["net_disbursement_amount"] == "38800.00"  # $40k - $1.2k

        # Underlying invoice transitions to APPROVED
        with Session(bind=db_engine) as session:
            inv_e = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.APPROVED.value

        # ---------------------------------------------------------------------
        # Phase 4: Disbursement Execution ($38,800.00 Net Payout)
        # ---------------------------------------------------------------------
        disb_idemp_key = f"idemp-e2e-disb-{uuid.uuid4().hex}"
        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-STARLIGHT-TREASURY",
                "idempotency_key": disb_idemp_key,
            },
        )
        assert disb_resp.status_code == 201
        disb_data = disb_resp.json()
        assert disb_data["status"] == "COMPLETED"
        assert disb_data["amount"] == "38800.00"
        disb_id = disb_data["id"]

        # Safe Idempotency Replay
        replay_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-STARLIGHT-TREASURY",
                "idempotency_key": disb_idemp_key,
            },
        )
        assert replay_resp.status_code == 201
        assert replay_resp.json()["id"] == disb_id

        # Lifecycle Statuses post-disbursement
        with Session(bind=db_engine) as session:
            app_e = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_e is not None
            assert app_e.status == FinancingStatus.DISBURSED.value

            inv_e = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.FINANCED.value

        # Verify Initial 4-legged Disbursement Journal Balances
        acc_resp = client.get("/api/v1/ledger/accounts")
        assert acc_resp.status_code == 200
        accounts = {a["account_number"]: a for a in acc_resp.json()}
        assert accounts["1200"]["balance"] == "50000.00"  # Factoring Receivables
        assert accounts["2100"]["balance"] == "10000.00"  # Customer Reserve Payable
        assert accounts["4010"]["balance"] == "1200.00"  # Factoring Fee Revenue
        assert accounts["1010"]["balance"] == "-38800.00"  # Cash Outflow

        # ---------------------------------------------------------------------
        # Phase 5: Debtor Collection #1 (Partial Payment $30,000.00)
        # ---------------------------------------------------------------------
        p1_idemp = f"idemp-e2e-p1-{uuid.uuid4().hex}"
        p1_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "30000.00",
                "settlement_fee": "0.00",
                "idempotency_key": p1_idemp,
            },
        )
        assert p1_resp.status_code == 200
        p1_data = p1_resp.json()
        assert p1_data["status"] == SettlementStatus.SHORTFALL.value
        assert p1_data["repayment_amount"] == "30000.00"
        assert p1_data["principal_repaid"] == "30000.00"
        assert p1_data["reserve_amount"] == "0.00"
        assert p1_data["net_reserve_refunded"] == "0.00"

        with Session(bind=db_engine) as session:
            app_e = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_e is not None
            assert app_e.status == FinancingStatus.PARTIALLY_SETTLED.value

            inv_e = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.FINANCED.value

        acc_resp1 = client.get("/api/v1/ledger/accounts")
        accounts1 = {a["account_number"]: a for a in acc_resp1.json()}
        assert accounts1["1200"]["balance"] == "20000.00"  # $50k - $30k = $20k remaining
        assert accounts1["2100"]["balance"] == "10000.00"  # Reserve liability remains intact
        assert accounts1["1010"]["balance"] == "-8800.00"  # -$38.8k + $30k

        # ---------------------------------------------------------------------
        # Phase 6: Debtor Collection #2 (Final $20,000.00 + $100 Settlement Fee)
        # ---------------------------------------------------------------------
        p2_idemp = f"idemp-e2e-p2-{uuid.uuid4().hex}"
        p2_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "20000.00",
                "settlement_fee": "100.00",
                "idempotency_key": p2_idemp,
            },
        )
        assert p2_resp.status_code == 200
        p2_data = p2_resp.json()
        assert p2_data["status"] == SettlementStatus.COMPLETED.value
        assert p2_data["repayment_amount"] == "20000.00"
        assert p2_data["principal_repaid"] == "10000.00"  # Completes $40k principal
        assert p2_data["reserve_amount"] == "10000.00"
        assert p2_data["settlement_fee"] == "100.00"
        assert p2_data["net_reserve_refunded"] == "9900.00"  # $10k - $100

        with Session(bind=db_engine) as session:
            app_e = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app_e is not None
            assert app_e.status == FinancingStatus.SETTLED.value

            inv_e = session.get(Invoice, uuid.UUID(inv_id))
            assert inv_e is not None
            assert inv_e.status == InvoiceStatus.PAID.value

            settlements = list(
                session.scalars(
                    select(Settlement).where(
                        Settlement.financing_application_id == uuid.UUID(app_id)
                    )
                )
            )
            assert len(settlements) == 2

        # ---------------------------------------------------------------------
        # Phase 7: Financial Ledger Zeroing & Reconciliation
        # ---------------------------------------------------------------------
        acc_resp_final = client.get("/api/v1/ledger/accounts")
        assert acc_resp_final.status_code == 200
        final_accs = {a["account_number"]: a for a in acc_resp_final.json()}

        # 1. Factoring Receivables must be completely zeroed out
        assert final_accs["1200"]["balance"] == "0.00"

        # 2. Customer Reserve Payable must be completely zeroed out
        assert final_accs["2100"]["balance"] == "0.00"

        # 3. Factoring Fee Revenue reflects cumulative fee earnings ($1200 + $100)
        assert final_accs["4010"]["balance"] == "1300.00"

        # 4. Operating Cash reflects net cash retained (+ $1,300.00)
        # Math: -$38.8k (disb) + $30k (p1) + $20k (p2) - $9.9k (refund) = +$1.3k
        assert final_accs["1010"]["balance"] == "1300.00"

        # 5. Global Trial Balance is net zero
        recon_resp = client.get("/api/v1/ledger/reconciliation")
        assert recon_resp.status_code == 200
        recon_data = recon_resp.json()
        assert recon_data["is_balanced"] is True
        assert recon_data["discrepancy"] == "0.00"

        # ---------------------------------------------------------------------
        # Phase 8: Complete Audit Log Integrity
        # ---------------------------------------------------------------------
        with Session(bind=db_engine) as session:
            logs = list(
                session.scalars(
                    select(FinancingAuditLog)
                    .where(FinancingAuditLog.application_id == uuid.UUID(app_id))
                    .order_by(FinancingAuditLog.created_at)
                )
            )
            statuses = [(log.from_status, log.to_status) for log in logs]
            assert ("APPROVED", "DISBURSED") in statuses
            assert ("DISBURSED", "PARTIALLY_SETTLED") in statuses
            assert ("PARTIALLY_SETTLED", "SETTLED") in statuses
