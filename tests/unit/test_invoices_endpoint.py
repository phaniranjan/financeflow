import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from financeflow.core.exceptions import (
    InvalidInvoiceAmountError,
    InvalidInvoiceDateError,
)
from financeflow.main import app
from financeflow.services.invoice import get_invoice_service


class TestInvoiceEndpointExceptionMapping:
    """Unit tests for endpoint-level exception handlers and status code mappings."""

    @pytest.mark.unit
    def test_service_invalid_amount_error_maps_to_400(self) -> None:
        """Verify service InvalidInvoiceAmountError is translated to HTTP 400."""
        mock_service = MagicMock()
        mock_service.create_invoice.side_effect = InvalidInvoiceAmountError(
            "Invoice amount must be positive"
        )

        app.dependency_overrides[get_invoice_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/invoices",
                    json={
                        "business_id": str(uuid.uuid4()),
                        "invoice_number": "INV-MOCK-001",
                        "debtor_name": "Debtor",
                        "amount": "100.00",
                        "currency": "USD",
                        "issue_date": "2026-11-01",
                        "due_date": "2026-12-01",
                    },
                )
                assert response.status_code == 400
                assert response.json() == {"detail": "Invoice amount must be positive"}
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_service_invalid_date_error_maps_to_400(self) -> None:
        """Verify service InvalidInvoiceDateError is translated to HTTP 400."""
        mock_service = MagicMock()
        mock_service.create_invoice.side_effect = InvalidInvoiceDateError(
            "Due date cannot precede invoice issue date"
        )

        app.dependency_overrides[get_invoice_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/invoices",
                    json={
                        "business_id": str(uuid.uuid4()),
                        "invoice_number": "INV-MOCK-002",
                        "debtor_name": "Debtor",
                        "amount": "100.00",
                        "currency": "USD",
                        "issue_date": "2026-11-01",
                        "due_date": "2026-12-01",
                    },
                )
                assert response.status_code == 400
                assert response.json() == {"detail": "Due date cannot precede invoice issue date"}
        finally:
            app.dependency_overrides.clear()
