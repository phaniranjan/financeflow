import uuid
from datetime import UTC, datetime

from financeflow.integrations.disbursement.provider import (
    DisbursementProvider,
    DisbursementRequest,
    DisbursementResult,
    DisbursementStatus,
)


class SimulatedDisbursementProvider(DisbursementProvider):
    """Simulated payment provider implementation with idempotency caching and fault injection."""

    def __init__(
        self,
        always_fail: bool = False,
        failure_message: str = "Payment transfer rejected by beneficiary bank",
        always_timeout: bool = False,
    ) -> None:
        self.always_fail = always_fail
        self.failure_message = failure_message
        self.always_timeout = always_timeout
        self._idempotency_cache: dict[str, DisbursementResult] = {}

    def disburse(self, request: DisbursementRequest) -> DisbursementResult:
        """Simulate disbursement execution with idempotency guarantees."""
        # 1. Return cached result if idempotency key was previously processed
        if request.idempotency_key in self._idempotency_cache:
            return self._idempotency_cache[request.idempotency_key]

        # 2. Inject timeout simulation
        if self.always_timeout:
            return DisbursementResult(
                status=DisbursementStatus.TIMEOUT,
                amount=request.amount,
                error_message="Gateway connection timeout",
            )

        # 3. Inject failure simulation
        if self.always_fail:
            return DisbursementResult(
                status=DisbursementStatus.FAILED,
                amount=request.amount,
                error_message=self.failure_message,
            )

        # 4. Successful execution simulation
        result = DisbursementResult(
            status=DisbursementStatus.COMPLETED,
            amount=request.amount,
            provider_transaction_id=f"sim_tx_{uuid.uuid4().hex[:12]}",
            disbursed_at=datetime.now(UTC),
        )

        self._idempotency_cache[request.idempotency_key] = result
        return result
