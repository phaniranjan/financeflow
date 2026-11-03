import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from financeflow.core.exceptions import (
    DuplicateSettlementError,
    FinancingApplicationNotFoundError,
    InvalidSettlementAmountError,
    InvalidSettlementStateError,
)
from financeflow.main import app
from financeflow.models.settlement import Settlement, SettlementStatus
from financeflow.services.settlement import get_settlement_service


class TestSettlementEndpoints:
    """Unit tests for settlement HTTP endpoints and exception handling."""

    @pytest.mark.unit
    def test_execute_settlement_success(self) -> None:
        """Successful settlement returns 200 OK and serialized response."""
        app_id = uuid.uuid4()
        s_id = uuid.uuid4()
        now = datetime.now(UTC)

        mock_settlement = Settlement(
            id=s_id,
            financing_application_id=app_id,
            invoice_id=uuid.uuid4(),
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("100.00"),
            net_reserve_refunded=Decimal("9900.00"),
            status=SettlementStatus.COMPLETED.value,
            idempotency_key="idemp-ep-01",
            settled_at=now,
            created_at=now,
            updated_at=now,
        )

        mock_service = MagicMock()
        mock_service.execute_settlement.return_value = mock_settlement

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/financing/{app_id}/settle",
                    json={
                        "repayment_amount": "50000.00",
                        "settlement_fee": "100.00",
                        "idempotency_key": "idemp-ep-01",
                        "correlation_id": "corr-001",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["id"] == str(s_id)
                assert data["financing_application_id"] == str(app_id)
                assert data["repayment_amount"] == "50000.00"
                assert data["principal_repaid"] == "40000.00"
                assert data["status"] == "COMPLETED"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("exc", "expected_status"),
        [
            (FinancingApplicationNotFoundError("Application missing"), 404),
            (DuplicateSettlementError("Already settled"), 409),
            (InvalidSettlementStateError("Must be DISBURSED"), 422),
            (InvalidSettlementAmountError("Fee exceeds reserve"), 400),
        ],
    )
    def test_execute_settlement_exception_mappings(
        self, exc: Exception, expected_status: int
    ) -> None:
        """Verify domain exceptions map to appropriate HTTP status codes."""
        app_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.execute_settlement.side_effect = exc

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/financing/{app_id}/settle",
                    json={
                        "repayment_amount": "50000.00",
                        "idempotency_key": "idemp-ep-02",
                    },
                )
                assert response.status_code == expected_status
                assert response.json()["detail"] == str(exc)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_settlement_by_application_success(self) -> None:
        """Retrieve settlement by application ID returns 200 OK."""
        app_id = uuid.uuid4()
        now = datetime.now(UTC)
        mock_s = Settlement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            invoice_id=uuid.uuid4(),
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("10000.00"),
            status="COMPLETED",
            idempotency_key="idemp-app-1",
            settled_at=now,
            created_at=now,
            updated_at=now,
        )
        mock_service = MagicMock()
        mock_service.get_settlement_by_application.return_value = mock_s

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/financing/{app_id}/settlement")
                assert response.status_code == 200
                assert response.json()["idempotency_key"] == "idemp-app-1"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_settlement_by_application_not_found_returns_404(self) -> None:
        """Returns 404 when no settlement exists for application."""
        app_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.get_settlement_by_application.return_value = None

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/financing/{app_id}/settlement")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_settlement_by_id_success(self) -> None:
        """Retrieve settlement by UUID returns 200 OK."""
        s_id = uuid.uuid4()
        now = datetime.now(UTC)
        mock_s = Settlement(
            id=s_id,
            financing_application_id=uuid.uuid4(),
            invoice_id=uuid.uuid4(),
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("10000.00"),
            status="COMPLETED",
            idempotency_key="idemp-s-1",
            settled_at=now,
            created_at=now,
            updated_at=now,
        )
        mock_service = MagicMock()
        mock_service.get_settlement.return_value = mock_s

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/settlements/{s_id}")
                assert response.status_code == 200
                assert response.json()["id"] == str(s_id)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_settlement_by_id_not_found_returns_404(self) -> None:
        """Returns 404 when settlement ID is not found."""
        s_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.get_settlement.return_value = None

        app.dependency_overrides[get_settlement_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get(f"/api/v1/settlements/{s_id}")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
