import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from financeflow.main import app
from financeflow.models.ledger import AccountType, LedgerAccount
from financeflow.services.ledger import get_ledger_service


class TestLedgerEndpoints:
    """Unit tests for ledger HTTP endpoints."""

    @pytest.mark.unit
    def test_list_ledger_accounts(self) -> None:
        """GET /api/v1/ledger/accounts returns list of accounts with their balances."""
        now = datetime.now(UTC)
        acc1 = LedgerAccount(
            id=uuid.uuid4(),
            account_number="1010",
            name="Operating Cash",
            account_type=AccountType.ASSET.value,
            created_at=now,
        )
        acc2 = LedgerAccount(
            id=uuid.uuid4(),
            account_number="1200",
            name="Factoring Receivables",
            account_type=AccountType.ASSET.value,
            created_at=now,
        )

        mock_service = MagicMock()
        mock_service.list_accounts_with_balances.return_value = [
            (acc1, Decimal("100000.00")),
            (acc2, Decimal("40000.00")),
        ]

        app.dependency_overrides[get_ledger_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/ledger/accounts")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 2
                assert data[0]["account_number"] == "1010"
                assert data[0]["balance"] == "100000.00"
                assert data[1]["account_number"] == "1200"
                assert data[1]["balance"] == "40000.00"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_reconcile_ledger(self) -> None:
        """GET /api/v1/ledger/reconciliation returns trial balance results."""
        mock_service = MagicMock()
        mock_service.reconcile_ledger.return_value = {
            "is_balanced": True,
            "total_debits": Decimal("50000.00"),
            "total_credits": Decimal("50000.00"),
            "discrepancy": Decimal("0.00"),
        }

        app.dependency_overrides[get_ledger_service] = lambda: mock_service
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/ledger/reconciliation")
                assert response.status_code == 200
                data = response.json()
                assert data["is_balanced"] is True
                assert data["total_debits"] == "50000.00"
                assert data["total_credits"] == "50000.00"
                assert data["discrepancy"] == "0.00"
        finally:
            app.dependency_overrides.clear()
