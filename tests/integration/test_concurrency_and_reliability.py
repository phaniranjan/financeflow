"""Integration tests for concurrency, fault injection, and boundary conditions (Cycle 7.1)."""

import concurrent.futures
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.db.session import get_db
from financeflow.integrations.disbursement.provider import (
    DisbursementProvider,
    DisbursementRequest,
    DisbursementResult,
)
from financeflow.main import app
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.business import Business, BusinessStatus
from financeflow.models.disbursement import Disbursement
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.repositories.audit import AuditRepository
from financeflow.repositories.disbursement import DisbursementRepository
from financeflow.repositories.financing import FinancingRepository
from financeflow.repositories.invoice import InvoiceRepository
from financeflow.services.disbursement import DisbursementService, get_disbursement_service
from financeflow.services.ledger import get_ledger_service

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
            tax_id=f"TAX-CONC-{uuid.uuid4().hex[:8]}",
            legal_name="Apex Concurrency Corp",
            status=BusinessStatus.ACTIVE.value,
        )
        session.add(business)
        session.commit()
        return business.id


@pytest.fixture
def submitted_invoice(db_engine, active_business: uuid.UUID) -> uuid.UUID:
    """Seed a submitted invoice for testing."""
    with Session(bind=db_engine) as session:
        invoice = Invoice(
            business_id=active_business,
            invoice_number=f"INV-CONC-{uuid.uuid4().hex[:8]}",
            debtor_name="MegaCorp Concurrency",
            amount=Decimal("50000.00"),
            currency="USD",
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 4, 1),
            status=InvoiceStatus.SUBMITTED.value,
        )
        session.add(invoice)
        session.commit()
        return invoice.id


class FaultyProvider(DisbursementProvider):
    """Provider that simulates unexpected network timeouts and 5xx failures."""

    def disburse(self, _request: DisbursementRequest) -> DisbursementResult:
        raise TimeoutError("Downstream payment gateway timed out after 10000ms")


class TestConcurrencyAndReliabilityIntegration:
    """Integration suite verifying concurrency locks, failure recovery, and boundaries."""

    @pytest.mark.integration
    def test_concurrent_disbursement_requests_serialized(
        self,
        client: TestClient,
        db_engine,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify concurrent disbursement calls result in exactly 1 success and 409s."""
        # 1. Create and approve application
        app_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "50000.00",
                "advance_rate": "0.8000",
                "fee_rate": "0.0300",
            },
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        approve_resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
        assert approve_resp.status_code == 200

        # 2. Concurrently attempt 5 disbursements
        def send_disbursement(i: int) -> int:
            resp = client.post(
                f"/api/v1/financing/{app_id}/disburse",
                json={
                    "recipient_account": f"ACC-CONCURRENT-{i}",
                    "idempotency_key": f"idemp-concurrent-{uuid.uuid4().hex}",
                },
            )
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_disbursement, i) for i in range(5)]
            status_codes = [f.result() for f in futures]

        # Exactly 1 request must succeed (201 Created); other 4 must be rejected with 409 Conflict
        assert status_codes.count(201) == 1
        assert status_codes.count(409) == 4

        # 3. Verify exactly 1 disbursement in database
        with Session(bind=db_engine) as session:
            disbursements = list(
                session.scalars(
                    select(Disbursement).where(
                        Disbursement.financing_application_id == uuid.UUID(app_id)
                    )
                )
            )
            assert len(disbursements) == 1
            assert disbursements[0].status == "COMPLETED"

    @pytest.mark.integration
    def test_concurrent_approval_requests_serialized(
        self,
        client: TestClient,
        db_engine,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify concurrent approval calls result in exactly 1 success and 400s."""
        # 1. Create application in SUBMITTED state
        app_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "50000.00",
            },
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        def send_approval(_i: int) -> int:
            resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_approval, i) for i in range(5)]
            status_codes = [f.result() for f in futures]

        assert status_codes.count(200) == 1
        assert status_codes.count(400) == 4

        with Session(bind=db_engine) as session:
            app = session.get(FinancingApplication, uuid.UUID(app_id))
            assert app is not None
            assert app.status == FinancingStatus.APPROVED.value

    @pytest.mark.integration
    def test_provider_network_failure_returns_502_and_preserves_application_state(
        self,
        client: TestClient,
        db_engine,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify unhandled provider network failure yields 502 and writes audit entry."""
        # Create and approve
        app_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "50000.00",
            },
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]
        client.post(f"/api/v1/financing/{app_id}/approve", json={})

        # Override dependency with FaultyProvider
        def get_faulty_disbursement_service(
            db_session: Session = pytest.importorskip("fastapi").Depends(get_db),
        ) -> DisbursementService:
            return DisbursementService(
                session=db_session,
                financing_repo=FinancingRepository(db_session),
                disbursement_repo=DisbursementRepository(db_session),
                invoice_repo=InvoiceRepository(db_session),
                ledger_service=get_ledger_service(db_session),
                provider=FaultyProvider(),
                audit_repo=AuditRepository(db_session),
            )

        app.dependency_overrides[get_disbursement_service] = get_faulty_disbursement_service
        try:
            disb_resp = client.post(
                f"/api/v1/financing/{app_id}/disburse",
                json={
                    "recipient_account": "ACC-FAULT-1",
                    "idempotency_key": f"idemp-fault-{uuid.uuid4().hex}",
                },
            )
            assert disb_resp.status_code == 502
            assert "Downstream payment gateway timed out" in disb_resp.json()["detail"]

            # Application must still be in APPROVED status
            with Session(bind=db_engine) as session:
                app_e = session.get(FinancingApplication, uuid.UUID(app_id))
                assert app_e is not None
                assert app_e.status == FinancingStatus.APPROVED.value

                # Verify audit entry was persisted
                logs = list(
                    session.scalars(
                        select(FinancingAuditLog).where(
                            FinancingAuditLog.application_id == uuid.UUID(app_id)
                        )
                    )
                )
                assert any("timed out" in log.reason for log in logs)
        finally:
            app.dependency_overrides.pop(get_disbursement_service, None)

    @pytest.mark.integration
    def test_minimum_boundary_values_lifecycle(
        self,
        client: TestClient,
        db_engine,
        active_business: uuid.UUID,
    ) -> None:
        """Verify lifecycle for boundary transaction: $1.00 amount, 100% advance, 0% fee."""
        # 1. Create $1.00 invoice
        inv_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(active_business),
                "invoice_number": f"INV-MIN-{uuid.uuid4().hex[:6]}",
                "debtor_name": "Micro Debtor",
                "amount": "1.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
        )
        assert inv_resp.status_code == 201
        inv_id = inv_resp.json()["id"]

        # 2. Finance with 100% advance rate and 0% fee
        app_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": inv_id,
                "requested_amount": "1.00",
                "advance_rate": "1.0000",
                "fee_rate": "0.0000",
            },
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        # 3. Approve
        appr_resp = client.post(f"/api/v1/financing/{app_id}/approve", json={})
        assert appr_resp.status_code == 200
        app_data = appr_resp.json()
        assert app_data["approved_amount"] == "1.00"
        assert app_data["fee_amount"] == "0.00"
        assert app_data["net_disbursement_amount"] == "1.00"

        # 4. Disburse $1.00
        disb_resp = client.post(
            f"/api/v1/financing/{app_id}/disburse",
            json={
                "recipient_account": "ACC-MIN-1",
                "idempotency_key": f"idemp-min-{uuid.uuid4().hex}",
            },
        )
        assert disb_resp.status_code == 201
        assert disb_resp.json()["amount"] == "1.00"

        # 5. Settle $1.00
        settle_resp = client.post(
            f"/api/v1/financing/{app_id}/settle",
            json={
                "repayment_amount": "1.00",
                "settlement_fee": "0.00",
                "idempotency_key": f"idemp-settle-min-{uuid.uuid4().hex}",
            },
        )
        assert settle_resp.status_code == 200
        settle_data = settle_resp.json()
        assert settle_data["status"] == "COMPLETED"
        assert settle_data["principal_repaid"] == "1.00"
        assert settle_data["reserve_amount"] == "0.00"
        assert settle_data["net_reserve_refunded"] == "0.00"

        # 6. Verify invoice status is PAID
        with Session(bind=db_engine) as session:
            inv = session.get(Invoice, uuid.UUID(inv_id))
            assert inv is not None
            assert inv.status == InvoiceStatus.PAID.value
