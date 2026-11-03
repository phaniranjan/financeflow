"""Integration tests for security, authentication, and tenant isolation (Cycle 7.3)."""

import uuid

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from financeflow.core.config import Settings, get_settings
from financeflow.db.base import Base
from financeflow.main import app
from financeflow.models.business import Business, BusinessStatus

settings = get_settings()


@pytest.fixture(scope="module")
def db_engine():
    """Create a database engine connected to PostgreSQL."""
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


@pytest.fixture
def business_a(db_engine) -> uuid.UUID:
    """Seed tenant Business A."""
    with Session(bind=db_engine) as session:
        b = Business(
            tax_id=f"TAX-TENANT-A-{uuid.uuid4().hex[:6]}",
            legal_name="Tenant Alpha Corp",
            status=BusinessStatus.ACTIVE.value,
        )
        session.add(b)
        session.commit()
        return b.id


@pytest.fixture
def business_b(db_engine) -> uuid.UUID:
    """Seed tenant Business B."""
    with Session(bind=db_engine) as session:
        b = Business(
            tax_id=f"TAX-TENANT-B-{uuid.uuid4().hex[:6]}",
            legal_name="Tenant Beta Ltd",
            status=BusinessStatus.ACTIVE.value,
        )
        session.add(b)
        session.commit()
        return b.id


class TestSecurityAndTenantIsolationIntegration:
    """Integration test suite verifying tenant boundary enforcement and error sanitization."""

    @pytest.mark.integration
    def test_tenant_cannot_access_other_tenant_invoice(
        self,
        client: TestClient,
        business_a: uuid.UUID,
        business_b: uuid.UUID,
    ) -> None:
        """Verify Tenant B receives 403 Forbidden when accessing an invoice owned by Tenant A."""
        # 1. Tenant A creates an invoice
        create_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_a),
                "invoice_number": f"INV-A-{uuid.uuid4().hex[:6]}",
                "debtor_name": "Debtor One",
                "amount": "10000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-Business-Id": str(business_a)},
        )
        assert create_resp.status_code == 201
        inv_id = create_resp.json()["id"]

        # 2. Tenant A can retrieve its own invoice
        get_a_resp = client.get(
            f"/api/v1/invoices/{inv_id}",
            headers={"X-Business-Id": str(business_a)},
        )
        assert get_a_resp.status_code == 200
        assert get_a_resp.json()["id"] == inv_id

        # 3. Tenant B attempting to retrieve Tenant A's invoice gets 403 Forbidden
        get_b_resp = client.get(
            f"/api/v1/invoices/{inv_id}",
            headers={"X-Business-Id": str(business_b)},
        )
        assert get_b_resp.status_code == 403
        assert "Access denied" in get_b_resp.json()["detail"]

        # 4. Tenant B creating invoice claiming Tenant A's business_id gets 403
        spoofed_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_a),
                "invoice_number": f"INV-SPOOF-{uuid.uuid4().hex[:6]}",
                "debtor_name": "Debtor Spoof",
                "amount": "5000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-Business-Id": str(business_b)},
        )
        assert spoofed_resp.status_code == 403

        # 5. Tenant B attempting to list Tenant A's invoices gets 403 Forbidden
        list_b_resp = client.get(
            f"/api/v1/invoices?business_id={business_a}",
            headers={"X-Business-Id": str(business_b)},
        )
        assert list_b_resp.status_code == 403

    @pytest.mark.integration
    def test_tenant_cannot_access_other_tenant_financing_application(
        self,
        client: TestClient,
        business_a: uuid.UUID,
        business_b: uuid.UUID,
    ) -> None:
        """Verify Tenant B gets 403 Forbidden when accessing Tenant A's financing."""
        # 1. Create invoice for Tenant A
        inv_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_a),
                "invoice_number": f"INV-FIN-A-{uuid.uuid4().hex[:6]}",
                "debtor_name": "Debtor Alpha",
                "amount": "20000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-Business-Id": str(business_a)},
        )
        assert inv_resp.status_code == 201
        inv_id = inv_resp.json()["id"]

        # 2. Tenant A creates financing application
        app_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(business_a),
                "invoice_id": inv_id,
                "requested_amount": "20000.00",
            },
            headers={"X-Business-Id": str(business_a)},
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        # 3. Tenant B retrieving Tenant A's application gets 403 Forbidden
        get_b_resp = client.get(
            f"/api/v1/financing/{app_id}",
            headers={"X-Business-Id": str(business_b)},
        )
        assert get_b_resp.status_code == 403
        assert "Access denied" in get_b_resp.json()["detail"]

        # 4. Tenant B submitting financing for Tenant A gets 403 Forbidden
        submit_b_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(business_a),
                "invoice_id": inv_id,
                "requested_amount": "20000.00",
            },
            headers={"X-Business-Id": str(business_b)},
        )
        assert submit_b_resp.status_code == 403

        # 5. Tenant B querying financing list for Tenant A gets 403 Forbidden
        list_b_resp = client.get(
            f"/api/v1/financing?business_id={business_a}",
            headers={"X-Business-Id": str(business_b)},
        )
        assert list_b_resp.status_code == 403

    @pytest.mark.integration
    def test_api_key_authentication_enforcement(
        self,
        client: TestClient,
        business_a: uuid.UUID,
    ) -> None:
        """Verify API key authentication enforcement when api_key_required is active."""
        strict_settings = Settings(
            api_key="financeflow_production_token",
            api_key_required=True,
        )

        app.dependency_overrides[get_settings] = lambda: strict_settings
        try:
            # 1. Missing API key returns 401 Unauthorized
            missing_resp = client.get(
                f"/api/v1/invoices?business_id={business_a}",
            )
            assert missing_resp.status_code == 401
            assert "Invalid or missing API Key" in missing_resp.json()["detail"]

            # 2. Invalid API key returns 401 Unauthorized
            bad_key_resp = client.get(
                f"/api/v1/invoices?business_id={business_a}",
                headers={"X-API-Key": "wrong-secret-token"},
            )
            assert bad_key_resp.status_code == 401

            # 3. Valid API key returns 200 OK
            valid_resp = client.get(
                f"/api/v1/invoices?business_id={business_a}",
                headers={"X-API-Key": "financeflow_production_token"},
            )
            assert valid_resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_settings, None)

    @pytest.mark.integration
    def test_global_exception_sanitizer_prevents_sensitive_leakage(
        self,
    ) -> None:
        """Verify unhandled 500 errors return sanitized response without leaking internals."""
        # Dynamically attach a temporary test endpoint that throws an unhandled exception
        test_crash_router = APIRouter()

        @test_crash_router.get("/api/v1/test-crash")
        def crash_endpoint() -> None:
            raise RuntimeError(
                "CRITICAL_DATABASE_ERROR: connection to secret_db@10.0.0.1:5432 failed"
            )

        app.include_router(test_crash_router)
        client_no_raise = TestClient(app, raise_server_exceptions=False)

        try:
            resp = client_no_raise.get("/api/v1/test-crash")
            assert resp.status_code == 500
            data = resp.json()

            # Must contain clean message and correlation ID
            assert "Internal server error" in data["detail"]
            assert "correlation_id" in data

            # Must NOT leak secret database connection info or stack trace in body
            assert "CRITICAL_DATABASE_ERROR" not in str(data)
            assert "secret_db" not in str(data)
            assert "10.0.0.1" not in str(data)
        finally:
            # Clean up test router
            app.routes[:] = [
                r for r in app.routes if getattr(r, "path", "") != "/api/v1/test-crash"
            ]
