import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.main import app
from financeflow.models.business import Business, BusinessStatus
from financeflow.models.financing import FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus

settings = get_settings()


@pytest.fixture(scope="module")
def db_engine() -> Generator[Engine, None, None]:
    """Create a database engine connected to the PostgreSQL instance."""
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(db_engine: Engine) -> Generator[TestClient, None, None]:
    """Provide a FastAPI TestClient configured for the test database."""
    assert db_engine is not None
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def active_business(db_engine: Engine) -> uuid.UUID:
    """Seed an active business for testing financing endpoints."""
    with Session(bind=db_engine) as session:
        business = Business(
            tax_id=f"TAX-FIN-{uuid.uuid4().hex[:8]}",
            legal_name="Apex Global Trade LLC",
            status=BusinessStatus.ACTIVE.value,
        )
        session.add(business)
        session.commit()
        session.refresh(business)
        b_id = business.id
    return b_id


@pytest.fixture
def suspended_business(db_engine: Engine) -> uuid.UUID:
    """Seed a suspended business for testing business rule validation."""
    with Session(bind=db_engine) as session:
        business = Business(
            tax_id=f"TAX-FIN-SUS-{uuid.uuid4().hex[:8]}",
            legal_name="Suspended Logistics Inc",
            status=BusinessStatus.SUSPENDED.value,
        )
        session.add(business)
        session.commit()
        session.refresh(business)
        b_id = business.id
    return b_id


@pytest.fixture
def submitted_invoice(db_engine: Engine, active_business: uuid.UUID) -> uuid.UUID:
    """Seed a submitted invoice eligible for financing."""
    with Session(bind=db_engine) as session:
        invoice = Invoice(
            business_id=active_business,
            invoice_number=f"INV-FIN-{uuid.uuid4().hex[:6]}",
            debtor_name="Target Corp",
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
def paid_invoice(db_engine: Engine, active_business: uuid.UUID) -> uuid.UUID:
    """Seed an ineligible invoice in PAID status."""
    with Session(bind=db_engine) as session:
        invoice = Invoice(
            business_id=active_business,
            invoice_number=f"INV-PAID-{uuid.uuid4().hex[:6]}",
            debtor_name="Walmart Stores",
            amount=Decimal("20000.00"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status=InvoiceStatus.PAID.value,
        )
        session.add(invoice)
        session.commit()
        session.refresh(invoice)
        inv_id = invoice.id
    return inv_id


class TestFinancingApiIntegration:
    """End-to-end integration tests for Financing REST API endpoints against PostgreSQL."""

    @pytest.mark.integration
    def test_create_financing_application_success(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify POST /api/v1/financing creates an application and returns 201 Created."""
        payload = {
            "business_id": str(active_business),
            "invoice_id": str(submitted_invoice),
            "requested_amount": "40000.00",
            "advance_rate": "0.8000",
            "fee_rate": "0.0300",
        }
        response = client.post("/api/v1/financing", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["business_id"] == str(active_business)
        assert data["invoice_id"] == str(submitted_invoice)
        assert data["requested_amount"] == "40000.00"
        assert data["advance_rate"] == "0.8000"
        assert data["fee_rate"] == "0.0300"
        assert data["status"] == FinancingStatus.SUBMITTED.value
        assert data["approved_amount"] is None
        assert data["fee_amount"] is None
        assert data["net_disbursement_amount"] is None
        assert data["rejection_reason"] is None
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.integration
    def test_create_financing_application_defaults(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify default advance_rate (0.8000) and fee_rate (0.0300) when omitted."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-DEF-{uuid.uuid4().hex[:6]}",
                debtor_name="Best Buy",
                amount=Decimal("15000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        payload = {
            "business_id": str(active_business),
            "invoice_id": str(inv_id),
            "requested_amount": "12000.00",
        }
        response = client.post("/api/v1/financing", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["advance_rate"] == "0.8000"
        assert data["fee_rate"] == "0.0300"

    @pytest.mark.integration
    def test_get_financing_application_by_id(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify GET /api/v1/financing/{id} retrieves application details."""
        # Create application first
        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "30000.00",
                "advance_rate": "0.8500",
                "fee_rate": "0.0250",
            },
        )
        app_id = create_resp.json()["id"]

        get_resp = client.get(f"/api/v1/financing/{app_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == app_id
        assert data["requested_amount"] == "30000.00"
        assert data["advance_rate"] == "0.8500"
        assert data["fee_rate"] == "0.0250"

    @pytest.mark.integration
    def test_get_financing_application_not_found(self, client: TestClient) -> None:
        """Verify GET /api/v1/financing/{id} returns 404 for non-existent UUID."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/financing/{random_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_list_financing_applications_by_business(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify GET /api/v1/financing?business_id=... returns paginated list."""
        for i in range(2):
            with Session(bind=db_engine) as session:
                inv = Invoice(
                    business_id=active_business,
                    invoice_number=f"INV-LST-{i}-{uuid.uuid4().hex[:6]}",
                    debtor_name=f"Debtor {i}",
                    amount=Decimal("10000.00"),
                    currency="USD",
                    issue_date=date(2026, 11, 1),
                    due_date=date(2026, 12, 1),
                    status=InvoiceStatus.SUBMITTED.value,
                )
                session.add(inv)
                session.commit()
                inv_id = inv.id

            client.post(
                "/api/v1/financing",
                json={
                    "business_id": str(active_business),
                    "invoice_id": str(inv_id),
                    "requested_amount": "8000.00",
                },
            )

        response = client.get(f"/api/v1/financing?business_id={active_business}&limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
        assert data["limit"] == 10
        assert data["offset"] == 0

    @pytest.mark.integration
    def test_list_financing_applications_business_not_found(self, client: TestClient) -> None:
        """Verify listing applications for non-existent business returns 404."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/financing?business_id={random_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_approve_financing_application_success(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify approval calculates exact financial precision amounts and transitions invoice."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-APP-{uuid.uuid4().hex[:6]}",
                debtor_name="Home Depot",
                amount=Decimal("10000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "10000.00",
                "advance_rate": "0.8000",
                "fee_rate": "0.0300",
            },
        )
        app_id = create_resp.json()["id"]

        approve_resp = client.post(f"/api/v1/financing/{app_id}/approve")
        assert approve_resp.status_code == 200
        data = approve_resp.json()
        assert data["status"] == FinancingStatus.APPROVED.value
        # 10000.00 * 0.8000 = 8000.00
        assert data["approved_amount"] == "8000.00"
        # 8000.00 * 0.0300 = 240.00
        assert data["fee_amount"] == "240.00"
        # 8000.00 - 240.00 = 7760.00
        assert data["net_disbursement_amount"] == "7760.00"

        # Verify underlying invoice transitioned to APPROVED
        invoice_resp = client.get(f"/api/v1/invoices/{inv_id}")
        assert invoice_resp.json()["status"] == InvoiceStatus.APPROVED.value

    @pytest.mark.integration
    def test_approve_application_invalid_state_transition(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify approving an already approved application returns 400 Bad Request."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-DA-{uuid.uuid4().hex[:6]}",
                debtor_name="Kroger",
                amount=Decimal("5000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "4000.00",
            },
        )
        app_id = create_resp.json()["id"]

        client.post(f"/api/v1/financing/{app_id}/approve")
        second_resp = client.post(f"/api/v1/financing/{app_id}/approve")
        assert second_resp.status_code == 400
        assert "Cannot approve application" in second_resp.json()["detail"]

    @pytest.mark.integration
    def test_reject_financing_application_success(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify rejection records rejection status and optional reason."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-REJ-{uuid.uuid4().hex[:6]}",
                debtor_name="Target",
                amount=Decimal("8000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "6000.00",
            },
        )
        app_id = create_resp.json()["id"]

        reject_resp = client.post(
            f"/api/v1/financing/{app_id}/reject",
            json={"reason": "Debtor credit score below underwriting threshold"},
        )
        assert reject_resp.status_code == 200
        data = reject_resp.json()
        assert data["status"] == FinancingStatus.REJECTED.value
        assert data["rejection_reason"] == "Debtor credit score below underwriting threshold"

    @pytest.mark.integration
    def test_reject_application_without_body(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify rejecting without body succeeds and leaves reason None."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-RN-{uuid.uuid4().hex[:6]}",
                debtor_name="Target",
                amount=Decimal("8000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "6000.00",
            },
        )
        app_id = create_resp.json()["id"]

        reject_resp = client.post(f"/api/v1/financing/{app_id}/reject")
        assert reject_resp.status_code == 200
        data = reject_resp.json()
        assert data["status"] == FinancingStatus.REJECTED.value
        assert data["rejection_reason"] is None

    @pytest.mark.integration
    def test_reject_application_invalid_state_transition(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify rejecting an already rejected application returns 400 Bad Request."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=active_business,
                invoice_number=f"INV-DR-{uuid.uuid4().hex[:6]}",
                debtor_name="Costco",
                amount=Decimal("5000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        create_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "4000.00",
            },
        )
        app_id = create_resp.json()["id"]

        client.post(f"/api/v1/financing/{app_id}/reject")
        second_resp = client.post(f"/api/v1/financing/{app_id}/reject")
        assert second_resp.status_code == 400
        assert "Cannot reject application" in second_resp.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_rejects_float_payload(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify API rejects raw JSON floating-point numbers to protect decimal precision."""
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": 15000.50,
            },
        )
        assert response.status_code == 422
        assert "Floating-point values are rejected" in str(response.json())

    @pytest.mark.integration
    def test_create_financing_business_not_found(
        self,
        client: TestClient,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify 404 when submitting financing for non-existent business."""
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(uuid.uuid4()),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "10000.00",
            },
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_invoice_not_found(
        self,
        client: TestClient,
        active_business: uuid.UUID,
    ) -> None:
        """Verify 404 when submitting financing for non-existent invoice."""
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(uuid.uuid4()),
                "requested_amount": "10000.00",
            },
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_suspended_business_returns_400(
        self,
        client: TestClient,
        suspended_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify submitting financing for suspended business returns 400 Bad Request."""
        with Session(bind=db_engine) as session:
            inv = Invoice(
                business_id=suspended_business,
                invoice_number=f"INV-SB-{uuid.uuid4().hex[:6]}",
                debtor_name="Debtor",
                amount=Decimal("10000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(suspended_business),
                "invoice_id": str(inv_id),
                "requested_amount": "5000.00",
            },
        )
        assert response.status_code == 400
        assert "not active" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_invoice_wrong_business_returns_400(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify submitting financing with mismatching business returns 400 Bad Request."""
        # Create another business
        with Session(bind=db_engine) as session:
            other_b = Business(
                tax_id=f"TAX-OTH-{uuid.uuid4().hex[:8]}",
                legal_name="Other Business Corp",
                status=BusinessStatus.ACTIVE.value,
            )
            session.add(other_b)
            session.commit()
            other_b_id = other_b.id

            inv = Invoice(
                business_id=other_b_id,
                invoice_number=f"INV-OTH-{uuid.uuid4().hex[:6]}",
                debtor_name="Debtor",
                amount=Decimal("10000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(inv)
            session.commit()
            inv_id = inv.id

        # Try to finance other_b's invoice under active_business
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(inv_id),
                "requested_amount": "5000.00",
            },
        )
        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_ineligible_invoice_status_returns_400(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        paid_invoice: uuid.UUID,
    ) -> None:
        """Verify submitting financing for non-SUBMITTED invoice returns 400 Bad Request."""
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(paid_invoice),
                "requested_amount": "5000.00",
            },
        )
        assert response.status_code == 400
        assert "Only SUBMITTED invoices" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_amount_exceeds_invoice_returns_400(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify requested amount exceeding invoice amount returns 400 Bad Request."""
        response = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(active_business),
                "invoice_id": str(submitted_invoice),
                "requested_amount": "999999.00",
            },
        )
        assert response.status_code == 400
        assert "cannot exceed invoice" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_financing_duplicate_returns_409(
        self,
        client: TestClient,
        active_business: uuid.UUID,
        submitted_invoice: uuid.UUID,
    ) -> None:
        """Verify duplicate active financing application returns 409 Conflict."""
        payload = {
            "business_id": str(active_business),
            "invoice_id": str(submitted_invoice),
            "requested_amount": "10000.00",
        }
        resp1 = client.post("/api/v1/financing", json=payload)
        assert resp1.status_code == 201

        resp2 = client.post("/api/v1/financing", json=payload)
        assert resp2.status_code == 409
        assert "already has an active financing" in resp2.json()["detail"]

    @pytest.mark.integration
    def test_concurrent_financing_requests_race_condition(
        self,
        active_business: uuid.UUID,
        db_engine: Engine,
    ) -> None:
        """Verify concurrent financing requests for the same invoice are resolved safely by DB."""
        with Session(bind=db_engine) as session:
            invoice = Invoice(
                business_id=active_business,
                invoice_number=f"INV-CONC-{uuid.uuid4().hex[:6]}",
                debtor_name="Concurrent Debtor",
                amount=Decimal("30000.00"),
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
                status=InvoiceStatus.SUBMITTED.value,
            )
            session.add(invoice)
            session.commit()
            invoice_id = invoice.id

        payload = {
            "business_id": str(active_business),
            "invoice_id": str(invoice_id),
            "requested_amount": "20000.00",
            "advance_rate": "0.8000",
            "fee_rate": "0.0300",
        }

        def post_financing() -> int:
            with TestClient(app) as local_client:
                res = local_client.post("/api/v1/financing", json=payload)
                return int(res.status_code)

        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(post_financing) for _ in range(num_threads)]
            status_codes = [f.result() for f in as_completed(futures)]

        assert status_codes.count(201) == 1
        assert status_codes.count(409) == num_threads - 1
