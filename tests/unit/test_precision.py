from decimal import Decimal

import pytest

from financeflow.core.precision import (
    FinancingCalculationResult,
    calculate_financing,
    quantize_currency,
    quantize_rate,
)


class TestFinancialQuantization:
    """Tests for exact Decimal rounding policies using ROUND_HALF_UP."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (Decimal("0.005"), Decimal("0.01")),
            (Decimal("0.004"), Decimal("0.00")),
            (Decimal("1.005"), Decimal("1.01")),
            (Decimal("1.015"), Decimal("1.02")),
            (Decimal("100.005"), Decimal("100.01")),
            (Decimal("100.004"), Decimal("100.00")),
            (Decimal("0.000"), Decimal("0.00")),
        ],
    )
    def test_quantize_currency_round_half_up(self, input_val: Decimal, expected: Decimal) -> None:
        """Verify strict ROUND_HALF_UP rounding to 2 decimal places for currency."""
        assert quantize_currency(input_val) == expected

    @pytest.mark.unit
    def test_quantize_rate(self) -> None:
        """Verify rates are quantized to 4 decimal places."""
        assert quantize_rate(Decimal("0.80001")) == Decimal("0.8000")
        assert quantize_rate(Decimal("0.80005")) == Decimal("0.8001")

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_val", [10.5, 10, "10.00", None])
    def test_quantize_currency_rejects_non_decimal(self, invalid_val: object) -> None:
        with pytest.raises(TypeError, match="amount must be a Decimal"):
            quantize_currency(invalid_val)  # type: ignore[arg-type]

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_val", [0.8, 1, "0.8000", None])
    def test_quantize_rate_rejects_non_decimal(self, invalid_val: object) -> None:
        with pytest.raises(TypeError, match="rate must be a Decimal"):
            quantize_rate(invalid_val)  # type: ignore[arg-type]


class TestCalculateFinancingStandardAndEdgeCases:
    """Tests for core financing calculations and exact decimal invariants."""

    @pytest.mark.unit
    def test_reference_example_calculation(self) -> None:
        """Verify the reference calculation:
        $50,000.00 invoice, 80% advance, 3% fee -> $40,000 advance, $1,200 fee, $38,800 net.
        """
        invoice_amount = Decimal("50000.00")
        advance_rate = Decimal("0.8000")
        fee_rate = Decimal("0.0300")

        result: FinancingCalculationResult = calculate_financing(
            invoice_amount=invoice_amount,
            advance_rate=advance_rate,
            fee_rate=fee_rate,
        )

        assert result.invoice_amount == Decimal("50000.00")
        assert result.advance_rate == Decimal("0.8000")
        assert result.fee_rate == Decimal("0.0300")
        assert result.advance_amount == Decimal("40000.00")
        assert result.fee_amount == Decimal("1200.00")
        assert result.net_disbursement == Decimal("38800.00")

    @pytest.mark.unit
    def test_quantization_order_preservation(self) -> None:
        """Verify advance amount is quantized FIRST, then used to compute fee and net.

        Example:
        Invoice: $100.05
        Advance Rate: 0.8000 -> 100.05 * 0.8 = 80.0400 -> Advance = $80.04
        Fee Rate: 0.0300 -> 80.04 * 0.03 = 2.4012 -> Fee = $2.40
        Net Disbursement = 80.04 - 2.40 = $77.64
        """
        result = calculate_financing(
            invoice_amount=Decimal("100.05"),
            advance_rate=Decimal("0.8000"),
            fee_rate=Decimal("0.0300"),
        )
        assert result.advance_amount == Decimal("80.04")
        assert result.fee_amount == Decimal("2.40")
        assert result.net_disbursement == Decimal("77.64")

    @pytest.mark.unit
    def test_boundary_rates_full_advance_and_zero_fee(self) -> None:
        """Verify boundary where advance rate is 100% and fee rate is 0%."""
        result = calculate_financing(
            invoice_amount=Decimal("1000.00"),
            advance_rate=Decimal("1.0000"),
            fee_rate=Decimal("0.0000"),
        )
        assert result.advance_amount == Decimal("1000.00")
        assert result.fee_amount == Decimal("0.00")
        assert result.net_disbursement == Decimal("1000.00")

    @pytest.mark.unit
    def test_large_financial_amounts(self) -> None:
        """Verify precision is maintained with institutional-scale financial amounts."""
        result = calculate_financing(
            invoice_amount=Decimal("123456789.99"),
            advance_rate=Decimal("0.8500"),
            fee_rate=Decimal("0.0250"),
        )
        # 123456789.99 * 0.85 = 104938271.4915 -> 104938271.49
        assert result.advance_amount == Decimal("104938271.49")
        # 104938271.49 * 0.025 = 2623456.78725 -> 2623456.79
        assert result.fee_amount == Decimal("2623456.79")
        # 104938271.49 - 2623456.79 = 102314814.70
        assert result.net_disbursement == Decimal("102314814.70")


class TestCalculateFinancingInputRejection:
    """Tests for rejecting non-Decimal inputs, negative/zero values, and invalid rate intervals."""

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_amount", [50000.0, 50000, "50000.00", None])
    def test_reject_non_decimal_invoice_amount(self, invalid_amount: object) -> None:
        with pytest.raises(TypeError, match="invoice_amount must be a Decimal"):
            calculate_financing(
                invoice_amount=invalid_amount,  # type: ignore[arg-type]
                advance_rate=Decimal("0.8000"),
                fee_rate=Decimal("0.0300"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_rate", [0.8, 1, "0.80", None])
    def test_reject_non_decimal_advance_rate(self, invalid_rate: object) -> None:
        with pytest.raises(TypeError, match="advance_rate must be a Decimal"):
            calculate_financing(
                invoice_amount=Decimal("50000.00"),
                advance_rate=invalid_rate,  # type: ignore[arg-type]
                fee_rate=Decimal("0.0300"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("invalid_fee", [0.03, 0, "0.03", None])
    def test_reject_non_decimal_fee_rate(self, invalid_fee: object) -> None:
        with pytest.raises(TypeError, match="fee_rate must be a Decimal"):
            calculate_financing(
                invoice_amount=Decimal("50000.00"),
                advance_rate=Decimal("0.8000"),
                fee_rate=invalid_fee,  # type: ignore[arg-type]
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "zero_or_negative", [Decimal("0.00"), Decimal("-1.00"), Decimal("-50000.00")]
    )
    def test_reject_non_positive_invoice_amount(self, zero_or_negative: Decimal) -> None:
        with pytest.raises(ValueError, match="invoice_amount must be greater than zero"):
            calculate_financing(
                invoice_amount=zero_or_negative,
                advance_rate=Decimal("0.8000"),
                fee_rate=Decimal("0.0300"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "invalid_rate",
        [Decimal("0.0000"), Decimal("-0.1000"), Decimal("1.0001"), Decimal("2.0000")],
    )
    def test_reject_out_of_bounds_advance_rate(self, invalid_rate: Decimal) -> None:
        with pytest.raises(ValueError, match="advance_rate must be in the range"):
            calculate_financing(
                invoice_amount=Decimal("50000.00"),
                advance_rate=invalid_rate,
                fee_rate=Decimal("0.0300"),
            )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "invalid_rate", [Decimal("-0.0001"), Decimal("1.0001"), Decimal("1.5000")]
    )
    def test_reject_out_of_bounds_fee_rate(self, invalid_rate: Decimal) -> None:
        with pytest.raises(ValueError, match="fee_rate must be in the range"):
            calculate_financing(
                invoice_amount=Decimal("50000.00"),
                advance_rate=Decimal("0.8000"),
                fee_rate=invalid_rate,
            )
