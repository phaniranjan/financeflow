"""Integration tests for security, authentication, and tenant isolation (Cycle 7 Hardening)."""

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
    """Integration test suite verifying the comprehensive Cycle 7 Security Test Matrix."""

    @pytest.mark.integration
    def test_security_matrix_no_api_key_returns_401(
        self,
        client: TestClient,
    ) -> None:
        """Matrix Case 1: No API key -> 401 Unauthorized."""
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 401
        assert "Invalid or missing API Key" in resp.json()["detail"]

    @pytest.mark.integration
    def test_security_matrix_invalid_api_key_returns_401(
        self,
        client: TestClient,
    ) -> None:
        """Matrix Case 2: Invalid API key -> 401 Unauthorized."""
        resp = client.get(
            "/api/v1/invoices",
            headers={"X-API-Key": "invalid_unrecognized_key_123"},
        )
        assert resp.status_code == 401
        assert "Invalid or missing API Key" in resp.json()["detail"]

    @pytest.mark.integration
    def test_security_matrix_valid_key_no_tenant_identity_returns_403(
        self,
        client: TestClient,
    ) -> None:
        """Matrix Case 3: Valid key, no tenant identity -> 403 Forbidden."""
        custom_settings = Settings(
            api_key_required=True,
            api_keys={"sk_live_unassigned_key": "unassigned"},
            environment="test",
        )
        app.dependency_overrides[get_settings] = lambda: custom_settings
        try:
            resp = client.get(
                "/api/v1/invoices",
                headers={"X-API-Key": "sk_live_unassigned_key"},
            )
            assert resp.status_code == 403
            assert "not associated with any tenant" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_settings, None)

    @pytest.mark.integration
    def test_security_matrix_business_a_key_plus_business_b_header_returns_403(
        self,
        client: TestClient,
        business_a: uuid.UUID,
        business_b: uuid.UUID,
    ) -> None:
        """Matrix Case 4: Business A key + Business B header -> 403 Forbidden."""
        resp = client.get(
            "/api/v1/invoices",
            headers={
                "X-API-Key": f"test-key-{business_a}",
                "X-Business-Id": str(business_b),
            },
        )
        assert resp.status_code == 403
        assert "not authorized for the specified business tenant" in resp.json()["detail"]

    @pytest.mark.integration
    def test_security_matrix_business_a_key_plus_business_a_header_allowed(
        self,
        client: TestClient,
        business_a: uuid.UUID,
    ) -> None:
        """Matrix Case 5: Business A key + Business A header -> Allowed."""
        resp = client.get(
            "/api/v1/invoices",
            headers={
                "X-API-Key": f"test-key-{business_a}",
                "X-Business-Id": str(business_a),
            },
        )
        assert resp.status_code == 200

    @pytest.mark.integration
    def test_security_matrix_business_a_accesses_business_b_invoice_returns_403(
        self,
        client: TestClient,
        business_a: uuid.UUID,
        business_b: uuid.UUID,
    ) -> None:
        """Matrix Case 6: Business A accesses Business B invoice -> 403 Forbidden."""
        # 1. Tenant B creates an invoice
        create_resp = client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_b),
                "invoice_number": f"INV-B-{uuid.uuid4().hex[:6]}",
                "debtor_name": "Debtor Beta Corp",
                "amount": "15000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-API-Key": f"test-key-{business_b}"},
        )
        assert create_resp.status_code == 201
        inv_b_id = create_resp.json()["id"]

        # 2. Tenant A attempts to access Tenant B's invoice -> 403
        snoop_resp = client.get(
            f"/api/v1/invoices/{inv_b_id}",
            headers={"X-API-Key": f"test-key-{business_a}"},
        )
        assert snoop_resp.status_code == 403
        detail = snoop_resp.json()["detail"]
        assert "Invoice does not belong to the authenticated business tenant" in detail

    @pytest.mark.integration
    def test_security_matrix_business_a_lists_invoices_without_filter_returns_only_business_a(
        self,
        client: TestClient,
        business_a: uuid.UUID,
        business_b: uuid.UUID,
    ) -> None:
        """Matrix Case 7: Business A lists invoices without filter -> Only Business A invoices."""
        # 1. Create invoice for Business A
        inv_a = f"INV-A-LIST-{uuid.uuid4().hex[:6]}"
        client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_a),
                "invoice_number": inv_a,
                "debtor_name": "Debtor A",
                "amount": "10000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-API-Key": f"test-key-{business_a}"},
        )

        # 2. Create invoice for Business B
        inv_b = f"INV-B-LIST-{uuid.uuid4().hex[:6]}"
        client.post(
            "/api/v1/invoices",
            json={
                "business_id": str(business_b),
                "invoice_number": inv_b,
                "debtor_name": "Debtor B",
                "amount": "20000.00",
                "currency": "USD",
                "issue_date": "2026-03-01T00:00:00Z",
                "due_date": "2026-04-01T00:00:00Z",
            },
            headers={"X-API-Key": f"test-key-{business_b}"},
        )

        # 3. Business A queries invoice list without business_id filter
        list_resp = client.get(
            "/api/v1/invoices",
            headers={"X-API-Key": f"test-key-{business_a}"},
        )
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]

        # All returned items must strictly belong to Business A
        for item in items:
            assert item["business_id"] == str(business_a)
            assert item["business_id"] != str(business_b)

        # 4. Business A explicitly querying Business B invoices gets 403
        forbidden_list = client.get(
            f"/api/v1/invoices?business_id={business_b}",
            headers={"X-API-Key": f"test-key-{business_a}"},
        )
        assert forbidden_list.status_code == 403

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
            headers={"X-API-Key": f"test-key-{business_a}"},
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
            headers={"X-API-Key": f"test-key-{business_a}"},
        )
        assert app_resp.status_code == 201
        app_id = app_resp.json()["id"]

        # 3. Tenant B retrieving Tenant A's application gets 403 Forbidden
        get_b_resp = client.get(
            f"/api/v1/financing/{app_id}",
            headers={"X-API-Key": f"test-key-{business_b}"},
        )
        assert get_b_resp.status_code == 403
        b_detail = get_b_resp.json()["detail"]
        assert (
            "Financing application does not belong to the authenticated business tenant" in b_detail
        )

        # 4. Tenant B submitting financing claiming Tenant A's business_id gets 403 Forbidden
        submit_b_resp = client.post(
            "/api/v1/financing",
            json={
                "business_id": str(business_a),
                "invoice_id": inv_id,
                "requested_amount": "20000.00",
            },
            headers={"X-API-Key": f"test-key-{business_b}"},
        )
        assert submit_b_resp.status_code == 403

        # 5. Tenant B querying financing list for Tenant A gets 403 Forbidden
        list_b_resp = client.get(
            f"/api/v1/financing?business_id={business_a}",
            headers={"X-API-Key": f"test-key-{business_b}"},
        )
        assert list_b_resp.status_code == 403

    @pytest.mark.integration
    def test_global_exception_sanitizer_prevents_sensitive_leakage(
        self,
    ) -> None:
        """Verify unhandled 500 errors return sanitized response without leaking internals."""
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

            assert "Internal server error" in data["detail"]
            assert "correlation_id" in data
            assert "CRITICAL_DATABASE_ERROR" not in str(data)
            assert "secret_db" not in str(data)
            assert "10.0.0.1" not in str(data)
        finally:
            app.routes[:] = [
                r for r in app.routes if getattr(r, "path", "") != "/api/v1/test-crash"
            ]
