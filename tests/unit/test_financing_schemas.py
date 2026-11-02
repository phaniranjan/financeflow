import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.schemas.financing import (
    FinancingApplicationCreate,
    FinancingApplicationListResponse,
    FinancingApplicationResponse,
    FinancingDecisionRequest,
)


class TestFinancingSchemas:
    """Unit tests for financing Pydantic v2 schemas."""

    @pytest.mark.unit
    def test_valid_financing_application_create(self) -> None:
        """Verify valid application create schema instantiation."""
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        schema = FinancingApplicationCreate(
            business_id=b_id,
            invoice_id=inv_id,
            requested_amount=Decimal("15000.00"),
            advance_rate=Decimal("0.8500"),
            fee_rate=Decimal("0.0250"),
        )
        assert schema.business_id == b_id
        assert schema.invoice_id == inv_id
        assert schema.requested_amount == Decimal("15000.00")
        assert schema.advance_rate == Decimal("0.8500")
        assert schema.fee_rate == Decimal("0.0250")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"requested_amount": 15000.50},
            {"advance_rate": 0.85},
            {"fee_rate": 0.03},
        ],
    )
    def test_reject_floats_at_schema_boundary(self, kwargs: dict[str, object]) -> None:
        """Verify floating-point numbers are strictly rejected."""
        base_payload: dict[str, object] = {
            "business_id": uuid.uuid4(),
            "invoice_id": uuid.uuid4(),
            "requested_amount": Decimal("10000.00"),
            "advance_rate": Decimal("0.8000"),
            "fee_rate": Decimal("0.0300"),
        }
        base_payload.update(kwargs)
        with pytest.raises(
            ValidationError,
            match="Floating-point values are rejected to avoid precision loss",
        ):
            FinancingApplicationCreate(**base_payload)

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_amt", [Decimal("0.00"), Decimal("-50.00")])
    def test_reject_non_positive_requested_amount(self, bad_amt: Decimal) -> None:
        """Verify requested_amount > 0 constraint."""
        with pytest.raises(ValidationError, match="Input should be greater than 0"):
            FinancingApplicationCreate(
                business_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                requested_amount=bad_amt,
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "advance_rate",
        [Decimal("0.0000"), Decimal("1.0001")],
    )
    def test_reject_out_of_bounds_advance_rate(self, advance_rate: Decimal) -> None:
        """Verify advance_rate bounds."""
        with pytest.raises(ValidationError):
            FinancingApplicationCreate(
                business_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                requested_amount=Decimal("1000.00"),
                advance_rate=advance_rate,
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fee_rate",
        [Decimal("-0.0001"), Decimal("1.0001")],
    )
    def test_reject_out_of_bounds_fee_rate(self, fee_rate: Decimal) -> None:
        """Verify fee_rate bounds."""
        with pytest.raises(ValidationError):
            FinancingApplicationCreate(
                business_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                requested_amount=Decimal("1000.00"),
                fee_rate=fee_rate,
            )

    @pytest.mark.unit
    def test_financing_decision_request(self) -> None:
        """Verify decision request schema."""
        req = FinancingDecisionRequest(reason="Risk policy violation")
        assert req.reason == "Risk policy violation"

        empty_req = FinancingDecisionRequest()
        assert empty_req.reason is None

    @pytest.mark.unit
    def test_financing_response_from_orm(self) -> None:
        """Verify FinancingApplicationResponse from ORM model attributes."""
        app_id = uuid.uuid4()
        b_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        now = datetime.now(UTC)

        orm_app = FinancingApplication(
            id=app_id,
            business_id=b_id,
            invoice_id=inv_id,
            requested_amount=Decimal("10000.00"),
            approved_amount=Decimal("8000.00"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
            fee_amount=Decimal("240.00"),
            net_disbursement_amount=Decimal("7760.00"),
            status=FinancingStatus.APPROVED.value,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
        )

        resp = FinancingApplicationResponse.model_validate(orm_app)
        assert resp.id == app_id
        assert resp.approved_amount == Decimal("8000.00")
        assert resp.net_disbursement_amount == Decimal("7760.00")
        assert resp.status == "APPROVED"

    @pytest.mark.unit
    def test_financing_list_response(self) -> None:
        """Verify list response wrapper."""
        resp = FinancingApplicationListResponse(
            total=1,
            items=[],
            limit=50,
            offset=0,
        )
        assert resp.total == 1
        assert resp.items == []
        assert resp.limit == 50
        assert resp.offset == 0
