import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from financeflow.core.config import get_settings
from financeflow.db.base import Base
from financeflow.main import app
from financeflow.models.business import Business

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
    """Seed an active business for testing invoice endpoints."""
    with Session(bind=db_engine) as session:
        business = Business(
            tax_id=f"TAX-API-{uuid.uuid4().hex[:8]}",
            legal_name="API Testing Enterprise LLC",
            status="ACTIVE",
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
            tax_id=f"TAX-SUS-{uuid.uuid4().hex[:8]}",
            legal_name="Suspended Enterprise LLC",
            status="SUSPENDED",
        )
        session.add(business)
        session.commit()
        session.refresh(business)
        b_id = business.id
    return b_id


class TestInvoiceApiIntegration:
    """Integration tests for Invoice REST API endpoints against PostgreSQL."""

    @pytest.mark.integration
    def test_health_endpoint(self, client: TestClient) -> None:
        """Verify GET /health returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @pytest.mark.integration
    def test_create_invoice_success(self, client: TestClient, active_business: uuid.UUID) -> None:
        """Verify POST /api/v1/invoices creates an invoice and returns 201 Created."""
        payload = {
            "business_id": str(active_business),
            "invoice_number": "INV-API-001",
            "debtor_name": "Mega Logistics Inc",
            "amount": "45000.75",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        response = client.post("/api/v1/invoices", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["invoice_number"] == "INV-API-001"
        assert data["amount"] == "45000.75"
        assert data["status"] == "SUBMITTED"
        assert data["business_id"] == str(active_business)
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.integration
    def test_create_invoice_duplicate_returns_409(
        self, client: TestClient, active_business: uuid.UUID
    ) -> None:
        """Verify duplicate invoice number for the same business returns 409 Conflict."""
        payload = {
            "business_id": str(active_business),
            "invoice_number": "INV-DUP-TEST",
            "debtor_name": "Debtor A",
            "amount": "1000.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        resp1 = client.post("/api/v1/invoices", json=payload)
        assert resp1.status_code == 201

        resp2 = client.post("/api/v1/invoices", json=payload)
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"]

    @pytest.mark.integration
    def test_create_invoice_business_not_found_returns_404(self, client: TestClient) -> None:
        """Verify submitting an invoice for a non-existent business returns 404 Not Found."""
        random_id = str(uuid.uuid4())
        payload = {
            "business_id": random_id,
            "invoice_number": "INV-NO-BIZ",
            "debtor_name": "Debtor",
            "amount": "1000.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        response = client.post("/api/v1/invoices", json=payload)
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_invoice_suspended_business_returns_400(
        self, client: TestClient, suspended_business: uuid.UUID
    ) -> None:
        """Verify submitting an invoice for an inactive business returns 400 Bad Request."""
        payload = {
            "business_id": str(suspended_business),
            "invoice_number": "INV-SUS-001",
            "debtor_name": "Debtor",
            "amount": "1000.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        response = client.post("/api/v1/invoices", json=payload)
        assert response.status_code == 400
        assert "not active" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_invoice_validation_error_returns_422(
        self, client: TestClient, active_business: uuid.UUID
    ) -> None:
        """Verify invalid payload (due_date < issue_date or negative amount) returns 422."""
        # Due date before issue date
        payload = {
            "business_id": str(active_business),
            "invoice_number": "INV-BAD-DATE",
            "debtor_name": "Debtor",
            "amount": "1000.00",
            "currency": "USD",
            "issue_date": "2026-12-01",
            "due_date": "2026-11-01",
        }
        response = client.post("/api/v1/invoices", json=payload)
        assert response.status_code == 422

        # Non-positive amount
        bad_amount_payload = {
            "business_id": str(active_business),
            "invoice_number": "INV-BAD-AMT",
            "debtor_name": "Debtor",
            "amount": "0.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        response = client.post("/api/v1/invoices", json=bad_amount_payload)
        assert response.status_code == 422

    @pytest.mark.integration
    def test_get_invoice_by_id_success(
        self, client: TestClient, active_business: uuid.UUID
    ) -> None:
        """Verify GET /api/v1/invoices/{id} returns 200 OK with the invoice details."""
        create_payload = {
            "business_id": str(active_business),
            "invoice_number": "INV-GET-001",
            "debtor_name": "Debtor Retail",
            "amount": "8000.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }
        created = client.post("/api/v1/invoices", json=create_payload).json()
        invoice_id = created["id"]

        get_resp = client.get(f"/api/v1/invoices/{invoice_id}")
        assert get_resp.status_code == 200
        retrieved = get_resp.json()
        assert retrieved["id"] == invoice_id
        assert retrieved["invoice_number"] == "INV-GET-001"
        assert retrieved["amount"] == "8000.00"

    @pytest.mark.integration
    def test_get_invoice_not_found_returns_404(self, client: TestClient) -> None:
        """Verify GET /api/v1/invoices/{id} returns 404 Not Found for non-existent UUID."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/invoices/{random_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_list_invoices_by_business(
        self, client: TestClient, active_business: uuid.UUID
    ) -> None:
        """Verify GET /api/v1/invoices?business_id=... returns paginated list of invoices."""
        for i in range(2):
            client.post(
                "/api/v1/invoices",
                json={
                    "business_id": str(active_business),
                    "invoice_number": f"INV-LIST-{i}",
                    "debtor_name": "List Debtor",
                    "amount": f"{1000 * (i + 1)}.00",
                    "currency": "USD",
                    "issue_date": "2026-11-01",
                    "due_date": "2026-12-01",
                },
            )

        response = client.get(f"/api/v1/invoices?business_id={active_business}&limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
        assert data["limit"] == 10
        assert data["offset"] == 0

    @pytest.mark.integration
    def test_list_invoices_business_not_found_returns_404(self, client: TestClient) -> None:
        """Verify listing invoices for non-existent business returns 404 Not Found."""
        random_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/invoices?business_id={random_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.integration
    def test_create_invoice_rejects_float_payload(
        self, client: TestClient, active_business: uuid.UUID
    ) -> None:
        """Verify API rejects raw JSON floating-point numbers to protect decimal precision."""
        response = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(active_business),
                "invoice_number": "INV-FLOAT-ERR",
                "debtor_name": "Float Debtor",
                "amount": 1500.50,
                "currency": "USD",
                "issue_date": "2026-11-01",
                "due_date": "2026-12-01",
            },
        )
        assert response.status_code == 422
        assert "Floating-point values are rejected" in str(response.json())

    @pytest.mark.integration
    def test_concurrent_invoice_creation_race_condition(
        self, active_business: uuid.UUID
    ) -> None:
        """Verify concurrent requests for the same invoice are resolved by PostgreSQL."""
        invoice_number = f"INV-RACE-{uuid.uuid4().hex[:6]}"
        payload = {
            "business_id": str(active_business),
            "invoice_number": invoice_number,
            "debtor_name": "Concurrent Debtor",
            "amount": "25000.00",
            "currency": "USD",
            "issue_date": "2026-11-01",
            "due_date": "2026-12-01",
        }

        def post_invoice() -> int:
            with TestClient(app) as local_client:
                res = local_client.post("/api/v1/invoices", json=payload)
                return int(res.status_code)

        num_threads = 5
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(post_invoice) for _ in range(num_threads)]
            status_codes = [f.result() for f in as_completed(futures)]

        assert status_codes.count(201) == 1
        assert status_codes.count(409) == num_threads - 1
