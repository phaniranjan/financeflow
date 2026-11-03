import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from financeflow.core.exceptions import (
    BusinessInactiveError,
    BusinessNotFoundError,
    DuplicateFinancingError,
    FinancingApplicationNotFoundError,
    InvalidFinancingAmountError,
    InvalidFinancingStateTransitionError,
    InvalidFinancingTermsError,
    InvoiceNotEligibleError,
    InvoiceNotFoundError,
)
from financeflow.main import app
from financeflow.services.financing import get_financing_service


class TestFinancingEndpointExceptionMapping:
    """Unit tests for financing endpoint HTTP exception translation."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (BusinessNotFoundError("Business not found"), 404),
            (InvoiceNotFoundError("Invoice not found"), 404),
            (DuplicateFinancingError("Duplicate financing"), 409),
            (BusinessInactiveError("Business inactive"), 400),
            (InvoiceNotEligibleError("Invoice not eligible"), 400),
            (InvalidFinancingAmountError("Invalid amount"), 400),
            (InvalidFinancingTermsError("Invalid terms"), 400),
        ],
    )
    def test_create_application_exception_mappings(
        self, exc: Exception, expected_status: int
    ) -> None:
        """Verify domain exceptions map to appropriate HTTP status codes on create."""
        mock_service = MagicMock()
        mock_service.create_application.side_effect = exc

        biz_id = str(uuid.uuid4())
        app.dependency_overrides[get_financing_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                client.headers["X-API-Key"] = f"test-key-{biz_id}"
                response = client.post(
                    "/api/v1/financing",
                    json={
                        "business_id": biz_id,
                        "invoice_id": str(uuid.uuid4()),
                        "requested_amount": "5000.00",
                        "advance_rate": "0.8000",
                        "fee_rate": "0.0300",
                    },
                )
                assert response.status_code == expected_status
                assert response.json()["detail"] == str(exc)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_application_not_found_maps_to_404(self) -> None:
        """Verify get_application returns 404 when service returns None."""
        mock_service = MagicMock()
        mock_service.get_application.return_value = None

        app.dependency_overrides[get_financing_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                client.headers["X-API-Key"] = "test-key-00000000-0000-0000-0000-000000000000"
                response = client.get(f"/api/v1/financing/{uuid.uuid4()}")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_list_applications_business_not_found_maps_to_404(self) -> None:
        """Verify list_applications maps BusinessNotFoundError to 404."""
        mock_service = MagicMock()
        mock_service.list_applications_by_business.side_effect = BusinessNotFoundError(
            "Business missing"
        )

        b_id = str(uuid.uuid4())
        app.dependency_overrides[get_financing_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                client.headers["X-API-Key"] = f"test-key-{b_id}"
                response = client.get(f"/api/v1/financing?business_id={b_id}")
                assert response.status_code == 404
                assert response.json()["detail"] == "Business missing"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (FinancingApplicationNotFoundError("Not found"), 404),
            (InvalidFinancingStateTransitionError("Bad transition"), 400),
        ],
    )
    def test_approve_application_exception_mappings(
        self, exc: Exception, expected_status: int
    ) -> None:
        """Verify approve endpoint exception mappings."""
        mock_service = MagicMock()
        mock_service.get_application.return_value = None
        mock_service.approve_application.side_effect = exc

        app.dependency_overrides[get_financing_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                client.headers["X-API-Key"] = "test-key-00000000-0000-0000-0000-000000000000"
                response = client.post(f"/api/v1/financing/{uuid.uuid4()}/approve")
                assert response.status_code == expected_status
                assert response.json()["detail"] == str(exc)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (FinancingApplicationNotFoundError("Not found"), 404),
            (InvalidFinancingStateTransitionError("Bad transition"), 400),
        ],
    )
    def test_reject_application_exception_mappings(
        self, exc: Exception, expected_status: int
    ) -> None:
        """Verify reject endpoint exception mappings."""
        mock_service = MagicMock()
        mock_service.get_application.return_value = None
        mock_service.reject_application.side_effect = exc

        app.dependency_overrides[get_financing_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                client.headers["X-API-Key"] = "test-key-00000000-0000-0000-0000-000000000000"
                response = client.post(
                    f"/api/v1/financing/{uuid.uuid4()}/reject",
                    json={"reason": "Rejected"},
                )
                assert response.status_code == expected_status
                assert response.json()["detail"] == str(exc)
        finally:
            app.dependency_overrides.clear()
