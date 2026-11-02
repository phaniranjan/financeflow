import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financeflow.schemas.invoice import InvoiceCreate, InvoiceListResponse, InvoiceResponse


class TestInvoiceSchemas:
    """Unit tests for Pydantic v2 request/response schemas."""

    @pytest.mark.unit
    def test_valid_invoice_create(self) -> None:
        """Verify creating a valid InvoiceCreate schema."""
        b_id = uuid.uuid4()
        schema = InvoiceCreate(
            business_id=b_id,
            invoice_number="INV-2026-001",
            debtor_name="Acme Corp",
            amount=Decimal("12500.50"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        assert schema.business_id == b_id
        assert schema.invoice_number == "INV-2026-001"
        assert schema.amount == Decimal("12500.50")
        assert isinstance(schema.amount, Decimal)
        assert schema.currency == "USD"

    @pytest.mark.unit
    def test_invoice_create_currency_normalization(self) -> None:
        """Verify currency code is normalized to uppercase."""
        schema = InvoiceCreate(
            business_id=uuid.uuid4(),
            invoice_number="INV-001",
            debtor_name="Acme",
            amount=Decimal("100.00"),
            currency="eur",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        assert schema.currency == "EUR"

    @pytest.mark.unit
    def test_invoice_create_rejects_float_amount(self) -> None:
        """Verify float amounts are rejected at the schema boundary."""
        with pytest.raises(
            ValidationError,
            match="Floating-point values are rejected to avoid precision loss",
        ):
            InvoiceCreate(
                business_id=uuid.uuid4(),
                invoice_number="INV-FLOAT-001",
                debtor_name="Acme",
                amount=1500.50,
                currency="USD",
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_amount", [Decimal("0.00"), Decimal("-50.00")])
    def test_invoice_create_amount_must_be_positive(self, invalid_amount: Decimal) -> None:
        """Verify non-positive amounts are rejected."""
        with pytest.raises(ValidationError, match="Input should be greater than 0"):
            InvoiceCreate(
                business_id=uuid.uuid4(),
                invoice_number="INV-001",
                debtor_name="Acme",
                amount=invalid_amount,
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

    @pytest.mark.unit
    def test_invoice_create_due_date_must_be_after_or_equal_issue_date(self) -> None:
        """Verify validation error when due_date < issue_date."""
        with pytest.raises(ValidationError, match="due_date cannot precede issue_date"):
            InvoiceCreate(
                business_id=uuid.uuid4(),
                invoice_number="INV-001",
                debtor_name="Acme",
                amount=Decimal("100.00"),
                issue_date=date(2026, 12, 1),
                due_date=date(2026, 11, 1),
            )

    @pytest.mark.unit
    def test_invoice_create_whitespace_stripped(self) -> None:
        """Verify leading and trailing whitespace is stripped."""
        schema = InvoiceCreate(
            business_id=uuid.uuid4(),
            invoice_number="  INV-TRIM-001  ",
            debtor_name="   Acme Retail   ",
            amount=Decimal("100.00"),
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
        )
        assert schema.invoice_number == "INV-TRIM-001"
        assert schema.debtor_name == "Acme Retail"

    @pytest.mark.unit
    @pytest.mark.parametrize("blank_str", ["   ", "\t\n"])
    def test_invoice_create_blank_strings_rejected(self, blank_str: str) -> None:
        """Verify empty or whitespace-only strings are rejected."""
        with pytest.raises(ValidationError, match="Field cannot be empty or whitespace only"):
            InvoiceCreate(
                business_id=uuid.uuid4(),
                invoice_number=blank_str,
                debtor_name="Acme Retail",
                amount=Decimal("100.00"),
                issue_date=date(2026, 11, 1),
                due_date=date(2026, 12, 1),
            )

    @pytest.mark.unit
    def test_invoice_response_serialization(self) -> None:
        """Verify serialization from object / dictionary."""
        inv_id = uuid.uuid4()
        b_id = uuid.uuid4()
        now = datetime.now(UTC)

        data = {
            "id": inv_id,
            "business_id": b_id,
            "invoice_number": "INV-RESP-001",
            "debtor_name": "Debtor Corp",
            "amount": Decimal("25000.00"),
            "currency": "USD",
            "issue_date": date(2026, 11, 1),
            "due_date": date(2026, 12, 1),
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
        }

        resp = InvoiceResponse.model_validate(data)
        assert resp.id == inv_id
        assert resp.amount == Decimal("25000.00")
        assert resp.status == "SUBMITTED"

    @pytest.mark.unit
    def test_invoice_list_response(self) -> None:
        """Verify pagination wrapper schema."""
        inv_id = uuid.uuid4()
        b_id = uuid.uuid4()
        now = datetime.now(UTC)

        item = InvoiceResponse(
            id=inv_id,
            business_id=b_id,
            invoice_number="INV-001",
            debtor_name="Debtor",
            amount=Decimal("500.00"),
            currency="USD",
            issue_date=date(2026, 11, 1),
            due_date=date(2026, 12, 1),
            status="SUBMITTED",
            created_at=now,
            updated_at=now,
        )

        list_resp = InvoiceListResponse(
            items=[item],
            total=1,
            limit=10,
            offset=0,
        )
        assert list_resp.total == 1
        assert len(list_resp.items) == 1
