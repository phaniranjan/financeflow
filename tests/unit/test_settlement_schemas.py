import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.schemas.settlement import (
    SettlementRequest,
    SettlementResponse,
)


class TestSettlementSchemas:
    """Unit tests for settlement schemas and input validations."""

    @pytest.mark.unit
    def test_settlement_request_valid(self) -> None:
        """Valid settlement request with string decimals succeeds."""
        req = SettlementRequest(
            repayment_amount=Decimal("50000.00"),
            settlement_fee=Decimal("100.00"),
            idempotency_key="idemp-key-settle-1",
            correlation_id="corr-settle-1",
        )
        assert req.repayment_amount == Decimal("50000.00")
        assert req.settlement_fee == Decimal("100.00")
        assert req.idempotency_key == "idemp-key-settle-1"
        assert req.correlation_id == "corr-settle-1"

    @pytest.mark.unit
    def test_settlement_request_defaults(self) -> None:
        """Settlement fee defaults to 0.00 and correlation_id to None."""
        req = SettlementRequest(
            repayment_amount=Decimal("50000.00"),
            idempotency_key="idemp-key-settle-2",
        )
        assert req.settlement_fee == Decimal("0.00")
        assert req.correlation_id is None

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("amount", "fee"),
        [
            (50000.0, Decimal("0.00")),
            (Decimal("50000.00"), 50.0),
        ],
    )
    def test_reject_float_values(self, amount: object, fee: object) -> None:
        """Reject float types at API boundaries to protect monetary precision."""
        with pytest.raises(ValidationError, match="Floating-point values are rejected"):
            SettlementRequest(
                repayment_amount=amount,  # type: ignore[arg-type]
                settlement_fee=fee,  # type: ignore[arg-type]
                idempotency_key="idemp-key-float",
            )

    @pytest.mark.unit
    def test_settlement_response_serialization(self) -> None:
        """SettlementResponse serializes all required fields."""
        now = datetime.now(UTC)
        s_id = uuid.uuid4()
        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()

        resp = SettlementResponse(
            id=s_id,
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("50000.00"),
            principal_repaid=Decimal("40000.00"),
            reserve_amount=Decimal("10000.00"),
            settlement_fee=Decimal("100.00"),
            net_reserve_refunded=Decimal("9900.00"),
            status="COMPLETED",
            idempotency_key="idemp-settle-resp",
            settled_at=now,
            created_at=now,
            updated_at=now,
        )
        assert resp.id == s_id
        assert resp.repayment_amount == Decimal("50000.00")
        assert resp.principal_repaid == Decimal("40000.00")
        assert resp.status == "COMPLETED"
