import uuid
from decimal import Decimal

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financeflow.core.exceptions import (
    DuplicateSettlementError,
    FinancingApplicationNotFoundError,
    InvalidSettlementAmountError,
    InvalidSettlementStateError,
)
from financeflow.db.session import get_db
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.financing import FinancingStatus
from financeflow.models.invoice import InvoiceStatus
from financeflow.models.settlement import Settlement, SettlementStatus
from financeflow.repositories.audit import AuditRepository
from financeflow.repositories.financing import FinancingRepository
from financeflow.repositories.invoice import InvoiceRepository
from financeflow.repositories.settlement import SettlementRepository
from financeflow.services.ledger import LedgerService, get_ledger_service


class SettlementService:
    """Domain service managing debtor repayment collection and client reserve release."""

    def __init__(
        self,
        session: Session,
        settlement_repo: SettlementRepository,
        financing_repo: FinancingRepository,
        invoice_repo: InvoiceRepository,
        ledger_service: LedgerService,
        audit_repo: AuditRepository,
    ) -> None:
        self._session = session
        self._settlement_repo = settlement_repo
        self._financing_repo = financing_repo
        self._invoice_repo = invoice_repo
        self._ledger_service = ledger_service
        self._audit_repo = audit_repo

    def execute_settlement(
        self,
        application_id: uuid.UUID,
        repayment_amount: Decimal,
        settlement_fee: Decimal = Decimal("0.00"),
        idempotency_key: str = "",
        correlation_id: str | None = None,
    ) -> Settlement:
        """Execute debtor invoice collection, extinguishing receivables and refunding reserve."""
        corr_id = correlation_id or str(uuid.uuid4())

        # 1. Idempotency replay check
        existing_by_key = self._settlement_repo.get_by_idempotency_key(idempotency_key)
        if existing_by_key is not None:
            existing_fee = existing_by_key.settlement_fee or Decimal("0.00")
            expected_fee = settlement_fee or Decimal("0.00")
            if (
                existing_by_key.financing_application_id != application_id
                or existing_by_key.repayment_amount != repayment_amount
                or existing_fee != expected_fee
            ):
                raise DuplicateSettlementError(
                    f"Idempotency key '{idempotency_key}' was previously used "
                    f"with different parameters"
                )
            return existing_by_key

        # 2. Verify application existence with row-level lock
        application = self._financing_repo.get_by_id(application_id, for_update=True)
        if application is None:
            raise FinancingApplicationNotFoundError(f"Application {application_id} not found")

        # 3. State validation: DISBURSED and PARTIALLY_SETTLED can receive collections
        if application.status == FinancingStatus.SETTLED.value:
            raise DuplicateSettlementError(f"Application {application_id} has already been settled")
        if application.status not in (
            FinancingStatus.DISBURSED.value,
            FinancingStatus.PARTIALLY_SETTLED.value,
        ):
            raise InvalidSettlementStateError(
                f"Cannot settle application in '{application.status}' status"
            )

        # 4. Amount validation
        if repayment_amount <= Decimal("0.00"):
            raise InvalidSettlementAmountError(
                f"Repayment amount must be positive, got {repayment_amount}"
            )

        total_obligation = application.requested_amount
        approved_amount = application.approved_amount or Decimal("0.00")
        contractual_reserve = total_obligation - approved_amount

        prior_settlements = self._settlement_repo.list_by_application_id(application_id)
        prior_collected = sum(
            (s.repayment_amount for s in prior_settlements),
            start=Decimal("0.00"),
        )
        outstanding_receivable = total_obligation - prior_collected

        if repayment_amount > outstanding_receivable:
            raise InvalidSettlementAmountError(
                f"Repayment amount ({repayment_amount}) exceeds outstanding "
                f"receivable ({outstanding_receivable})"
            )

        prior_principal_collected = sum(
            (s.principal_repaid for s in prior_settlements),
            start=Decimal("0.00"),
        )
        remaining_principal = approved_amount - prior_principal_collected
        this_principal = min(repayment_amount, remaining_principal)

        new_total_collected = prior_collected + repayment_amount
        is_final = new_total_collected == total_obligation

        if not is_final:
            # Partial collection / shortfall
            principal_repaid = this_principal
            reserve_amount = Decimal("0.00")
            settlement_fee_applied = Decimal("0.00")
            net_reserve_refunded = Decimal("0.00")
            status_val = SettlementStatus.SHORTFALL.value
            target_app_status = FinancingStatus.PARTIALLY_SETTLED.value
        else:
            # Final collection completing the contractual obligation
            principal_repaid = this_principal
            reserve_amount = contractual_reserve
            if settlement_fee > reserve_amount:
                raise InvalidSettlementAmountError(
                    f"Settlement fee ({settlement_fee}) cannot exceed reserve ({reserve_amount})"
                )
            settlement_fee_applied = settlement_fee
            net_reserve_refunded = reserve_amount - settlement_fee_applied
            status_val = SettlementStatus.COMPLETED.value
            target_app_status = FinancingStatus.SETTLED.value

        settlement = Settlement(
            financing_application_id=application_id,
            invoice_id=application.invoice_id,
            repayment_amount=repayment_amount,
            principal_repaid=principal_repaid,
            reserve_amount=reserve_amount,
            settlement_fee=settlement_fee_applied,
            net_reserve_refunded=net_reserve_refunded,
            status=status_val,
            idempotency_key=idempotency_key,
        )

        try:
            self._settlement_repo.create(settlement)

            prior_status = application.status
            application.status = target_app_status

            # Transition invoice to PAID only on final settlement
            if is_final:
                invoice = self._invoice_repo.get_by_id(application.invoice_id)
                if invoice is not None:
                    invoice.status = InvoiceStatus.PAID.value

            # Post balanced 2-legged collection transaction (Cash debit, Receivables credit)
            self._ledger_service.post_settlement_transaction(
                application_id=application_id,
                repayment_amount=repayment_amount,
            )

            # If contractual settlement conditions are met, release reserve
            if is_final and reserve_amount > Decimal("0.00"):
                self._ledger_service.post_reserve_release_transaction(
                    application_id=application_id,
                    reserve_amount=reserve_amount,
                    settlement_fee=settlement_fee_applied,
                    net_refund_amount=net_reserve_refunded,
                )

            # Record audit log
            self._audit_repo.create(
                FinancingAuditLog(
                    application_id=application_id,
                    from_status=prior_status,
                    to_status=target_app_status,
                    actor="SETTLEMENT_SERVICE",
                    correlation_id=corr_id,
                    reason=(
                        f"Debtor collection {repayment_amount} recorded; status {target_app_status}"
                    ),
                )
            )

            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            err_str = str(exc).lower()
            if (
                "ix_settlements_idempotency_key" in err_str
                or "ix_settlements_financing_application_id" in err_str
                or "unique constraint" in err_str
            ):
                raise DuplicateSettlementError(
                    f"Settlement conflict for application {application_id}"
                ) from exc
            raise
        except Exception:
            self._session.rollback()
            raise

        return settlement

    def get_settlement(self, settlement_id: uuid.UUID) -> Settlement | None:
        """Retrieve a settlement record by its ID."""
        return self._settlement_repo.get_by_id(settlement_id)

    def get_settlement_by_application(self, application_id: uuid.UUID) -> Settlement | None:
        """Retrieve latest settlement associated with a specific financing application."""
        return self._settlement_repo.get_by_application_id(application_id)

    def get_settlements_by_application(self, application_id: uuid.UUID) -> list[Settlement]:
        """Retrieve all settlement records associated with a specific financing application."""
        return self._settlement_repo.list_by_application_id(application_id)


def get_settlement_service(
    session: Session = Depends(get_db),
    ledger_service: LedgerService = Depends(get_ledger_service),
) -> SettlementService:
    """FastAPI dependency provider injecting repositories into SettlementService."""
    settlement_repo = SettlementRepository(session)
    financing_repo = FinancingRepository(session)
    invoice_repo = InvoiceRepository(session)
    audit_repo = AuditRepository(session)
    return SettlementService(
        session=session,
        settlement_repo=settlement_repo,
        financing_repo=financing_repo,
        invoice_repo=invoice_repo,
        ledger_service=ledger_service,
        audit_repo=audit_repo,
    )
