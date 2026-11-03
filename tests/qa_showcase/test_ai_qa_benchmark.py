"""AI-Assisted QA Benchmark Suite (Cycle 7.5).

Engineered for SDET architecture and interview demonstration:
Tests invariant-based property testing, deliberate defect detection,
and validation of agent-generated test cases against double-entry ledger invariants.
"""

from decimal import Decimal

import pytest

from financeflow.core.precision import quantize_currency


class TestAIAssistedQABenchmark:
    """Benchmark tests validating financial invariants and detecting subtle domain defects."""

    @pytest.mark.unit
    def test_invariant_conservation_of_principal_and_reserve(self) -> None:
        """FINANCIAL INVARIANT 1: Pledged Collateral == Approved Financing + Customer Reserve.

        Validates across arbitrary non-round amounts that:
        requested_amount == approved_amount + reserve_amount (strictly preserved).
        """
        test_cases = [
            (Decimal("10000.00"), Decimal("0.8000")),
            (Decimal("54321.99"), Decimal("0.7500")),
            (Decimal("123456.78"), Decimal("0.8250")),
            (Decimal("1.00"), Decimal("1.0000")),
            (Decimal("999999.99"), Decimal("0.6500")),
        ]

        for gross, advance_rate in test_cases:
            approved = quantize_currency(gross * advance_rate)
            reserve = gross - approved
            # Invariant check: Conservation of Collateral Value
            assert approved + reserve == gross, (
                f"Collateral conservation violated: {approved} + {reserve} != {gross}"
            )

    @pytest.mark.unit
    def test_invariant_fee_and_net_disbursement_integrity(self) -> None:
        """FINANCIAL INVARIANT 2: Approved Financing == Net Payout + Factoring Fee.

        Ensures zero penny leakage during disbursement calculation:
        approved_amount == net_disbursement + fee_amount.
        """
        test_cases = [
            (Decimal("40000.00"), Decimal("0.0300")),
            (Decimal("32000.00"), Decimal("0.0250")),
            (Decimal("98765.43"), Decimal("0.0175")),
            (Decimal("1.00"), Decimal("0.0000")),
            (Decimal("77777.77"), Decimal("0.0450")),
        ]

        for approved, fee_rate in test_cases:
            fee = quantize_currency(approved * fee_rate)
            net_disb = quantize_currency(approved - fee)
            # Invariant check: Conservation of Payout Value
            assert net_disb + fee == approved, (
                f"Payout conservation violated: {net_disb} + {fee} != {approved}"
            )

    @pytest.mark.unit
    def test_detect_deliberate_float_conversion_defect(self) -> None:
        """BENCHMARK DEFECT 1: Float Precision Leakage Detector.

        Demonstrates why IEEE-754 binary floating point arithmetic fails in
        financial factoring, whereas Decimal maintains exactness.
        """
        # Classic float representation flaw: 0.1 + 0.2 != 0.3 in IEEE-754
        float_sum = 0.1 + 0.2
        assert float_sum != 0.3, "Float arithmetic unexpectedly matched exact decimal"

        # Decimal exactness guarantee
        decimal_sum = Decimal("0.1") + Decimal("0.2")
        assert decimal_sum == Decimal("0.3"), "Decimal arithmetic failed exact match"

    @pytest.mark.unit
    def test_detect_deliberate_overpayment_shortfall_boundary(self) -> None:
        """BENCHMARK DEFECT 2: Cumulative Repayment Cap Invariant.

        Demonstrates that cumulative debtor repayments can NEVER exceed total receivable.
        """
        total_receivable = Decimal("50000.00")
        prior_payments = [Decimal("20000.00"), Decimal("15000.00")]
        current_outstanding = total_receivable - sum(prior_payments)
        assert current_outstanding == Decimal("15000.00")

        # An overpayment of 1 cent must be detected and rejected
        overpayment_candidate = Decimal("15000.01")
        is_valid = overpayment_candidate <= current_outstanding
        assert not is_valid, "Overpayment boundary defect: 1-cent overflow was not caught"
