import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from financeflow.core.exceptions import (
    DisbursementExecutionError,
    DuplicateDisbursementError,
    FinancingApplicationNotFoundError,
    InvalidDisbursementStateError,
)
from financeflow.integrations.disbursement.provider import DisbursementStatus
from financeflow.main import app
from financeflow.models.disbursement import Disbursement
from financeflow.services.disbursement import get_disbursement_service


class TestDisbursementEndpoints:
    """Unit tests for disbursement HTTP endpoints and exception handling."""

    @pytest.mark.unit
    def test_execute_disbursement_success(self) -> None:
        """Successful disbursement execution returns 201 Created and serialized response."""
        app_id = uuid.uuid4()
        disb_id = uuid.uuid4()
        now = datetime.now(UTC)

        mock_disbursement = Disbursement(
            id=disb_id,
            financing_application_id=app_id,
            idempotency_key="idemp-test-01",
            amount=Decimal("38800.00"),
            recipient_account="ACC-9988",
            status=DisbursementStatus.COMPLETED.value,
            provider_transaction_id="TX-PROV-111",
            disbursed_at=now,
            created_at=now,
            updated_at=now,
        )

        mock_service = MagicMock()
        mock_service.execute_disbursement.return_value = mock_disbursement

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/financing/{app_id}/disburse",
                    json={
                        "recipient_account": "ACC-9988",
                        "idempotency_key": "idemp-test-01",
                        "correlation_id": "corr-001",
                    },
                )
                assert response.status_code == 201
                data = response.json()
                assert data["id"] == str(disb_id)
                assert data["financing_application_id"] == str(app_id)
                assert data["amount"] == "38800.00"
                assert data["status"] == "COMPLETED"
                assert data["provider_transaction_id"] == "TX-PROV-111"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (FinancingApplicationNotFoundError("Application not found"), 404),
            (DuplicateDisbursementError("Already disbursed"), 409),
            (InvalidDisbursementStateError("Must be in APPROVED state"), 422),
            (DisbursementExecutionError("Payment rail rejected transfer"), 502),
        ],
    )
    def test_execute_disbursement_exception_mappings(
        self, exc: Exception, expected_status: int
    ) -> None:
        """Verify domain exceptions map to appropriate HTTP status codes."""
        app_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.execute_disbursement.side_effect = exc

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/financing/{app_id}/disburse",
                    json={
                        "recipient_account": "ACC-9988",
                        "idempotency_key": "idemp-test-02",
                    },
                )
                assert response.status_code == expected_status
                assert response.json()["detail"] == str(exc)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_disbursement_by_application_success(self) -> None:
        """Retrieve disbursement by financing application ID returns 200 OK."""
        app_id = uuid.uuid4()
        now = datetime.now(UTC)
        mock_disb = Disbursement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            idempotency_key="idemp-app-1",
            amount=Decimal("38800.00"),
            recipient_account="ACC-1",
            status="COMPLETED",
            created_at=now,
            updated_at=now,
        )
        mock_service = MagicMock()
        mock_service.get_disbursement_by_application.return_value = mock_disb

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/financing/{app_id}/disbursement")
                assert response.status_code == 200
                assert response.json()["idempotency_key"] == "idemp-app-1"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_disbursement_by_application_not_found_returns_404(self) -> None:
        """Returns 404 when no disbursement exists for application."""
        app_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.get_disbursement_by_application.return_value = None

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/financing/{app_id}/disbursement")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_disbursement_by_id_success(self) -> None:
        """Retrieve disbursement by primary ID returns 200 OK."""
        disb_id = uuid.uuid4()
        now = datetime.now(UTC)
        mock_disb = Disbursement(
            id=disb_id,
            financing_application_id=uuid.uuid4(),
            idempotency_key="idemp-id-1",
            amount=Decimal("38800.00"),
            recipient_account="ACC-1",
            status="COMPLETED",
            created_at=now,
            updated_at=now,
        )
        mock_service = MagicMock()
        mock_service.get_disbursement.return_value = mock_disb

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/disbursements/{disb_id}")
                assert response.status_code == 200
                assert response.json()["id"] == str(disb_id)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_disbursement_by_id_not_found_returns_404(self) -> None:
        """Returns 404 when disbursement ID is not found."""
        disb_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.get_disbursement.return_value = None

        app.dependency_overrides[get_disbursement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/disbursements/{disb_id}")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
