from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# Quantization constants
CURRENCY_EXPONENT: Decimal = Decimal("0.01")
RATE_EXPONENT: Decimal = Decimal("0.0001")


def quantize_currency(amount: Decimal) -> Decimal:
    """Quantize a monetary amount to 2 decimal places using ROUND_HALF_UP."""
    if not isinstance(amount, Decimal):
        raise TypeError(f"amount must be a Decimal, got {type(amount).__name__}")
    return amount.quantize(CURRENCY_EXPONENT, rounding=ROUND_HALF_UP)


def quantize_rate(rate: Decimal) -> Decimal:
    """Quantize a percentage rate to 4 decimal places using ROUND_HALF_UP."""
    if not isinstance(rate, Decimal):
        raise TypeError(f"rate must be a Decimal, got {type(rate).__name__}")
    return rate.quantize(RATE_EXPONENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FinancingCalculationResult:
    """Immutable result structure containing the full breakdown of financing calculations."""

    invoice_amount: Decimal
    advance_rate: Decimal
    fee_rate: Decimal
    advance_amount: Decimal
    fee_amount: Decimal
    net_disbursement: Decimal


def calculate_financing(
    invoice_amount: Decimal,
    advance_rate: Decimal,
    fee_rate: Decimal,
) -> FinancingCalculationResult:
    """Calculate advance amount, platform fee, and net disbursement amount.

    Invariants enforced:
    1. Input types must strictly be Decimal (no floats, ints, or strings).
    2. invoice_amount > 0.00
    3. advance_rate in (0.0000, 1.0000]
    4. fee_rate in [0.0000, 1.0000]
    5. Advance amount is quantized first. Platform fee is computed from the
       quantized advance amount and quantized. Net disbursement is the exact
       difference: advance_amount - fee_amount.

    Formula:
        advance_amount = quantize(invoice_amount * advance_rate)
        fee_amount = quantize(advance_amount * fee_rate)
        net_disbursement = advance_amount - fee_amount
    """
    if not isinstance(invoice_amount, Decimal):
        raise TypeError(f"invoice_amount must be a Decimal, got {type(invoice_amount).__name__}")
    if not isinstance(advance_rate, Decimal):
        raise TypeError(f"advance_rate must be a Decimal, got {type(advance_rate).__name__}")
    if not isinstance(fee_rate, Decimal):
        raise TypeError(f"fee_rate must be a Decimal, got {type(fee_rate).__name__}")

    if invoice_amount <= Decimal("0.00"):
        raise ValueError("invoice_amount must be greater than zero")

    if not (Decimal("0.0000") < advance_rate <= Decimal("1.0000")):
        raise ValueError("advance_rate must be in the range (0.0000, 1.0000]")

    if not (Decimal("0.0000") <= fee_rate <= Decimal("1.0000")):
        raise ValueError("fee_rate must be in the range [0.0000, 1.0000]")

    sanitized_invoice = quantize_currency(invoice_amount)
    sanitized_advance_rate = quantize_rate(advance_rate)
    sanitized_fee_rate = quantize_rate(fee_rate)

    advance_amount = quantize_currency(sanitized_invoice * sanitized_advance_rate)
    fee_amount = quantize_currency(advance_amount * sanitized_fee_rate)
    net_disbursement = advance_amount - fee_amount

    return FinancingCalculationResult(
        invoice_amount=sanitized_invoice,
        advance_rate=sanitized_advance_rate,
        fee_rate=sanitized_fee_rate,
        advance_amount=advance_amount,
        fee_amount=fee_amount,
        net_disbursement=net_disbursement,
    )
