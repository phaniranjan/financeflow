import uuid

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financeflow.core.exceptions import (
    DisbursementExecutionError,
    DuplicateDisbursementError,
    FinancingApplicationNotFoundError,
    InvalidDisbursementStateError,
)
from financeflow.db.session import get_db
from financeflow.integrations.disbursement.provider import (
    DisbursementProvider,
    DisbursementRequest,
    DisbursementStatus,
)
from financeflow.integrations.disbursement.simulated import SimulatedDisbursementProvider
from financeflow.models.audit import FinancingAuditLog
from financeflow.models.disbursement import Disbursement
from financeflow.models.financing import FinancingStatus
from financeflow.models.invoice import InvoiceStatus
from financeflow.repositories.audit import AuditRepository
from financeflow.repositories.disbursement import DisbursementRepository
from financeflow.repositories.financing import FinancingRepository
from financeflow.repositories.invoice import InvoiceRepository
from financeflow.services.ledger import LedgerService, get_ledger_service


class DisbursementService:
    """Domain service managing reliable execution of disbursements and ledger postings."""

    def __init__(
        self,
        session: Session,
        disbursement_repo: DisbursementRepository,
        financing_repo: FinancingRepository,
        invoice_repo: InvoiceRepository,
        ledger_service: LedgerService,
        provider: DisbursementProvider,
        audit_repo: AuditRepository,
    ) -> None:
        self._session = session
        self._disbursement_repo = disbursement_repo
        self._financing_repo = financing_repo
        self._invoice_repo = invoice_repo
        self._ledger_service = ledger_service
        self._provider = provider
        self._audit_repo = audit_repo

    def execute_disbursement(
        self,
        application_id: uuid.UUID,
        recipient_account: str,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Disbursement:
        """Execute funds transfer for an approved financing application with idempotency."""
        corr_id = correlation_id or str(uuid.uuid4())

        # 1. Idempotency replay check: Return existing disbursement if idempotency_key was used
        existing_by_key = self._disbursement_repo.get_by_idempotency_key(idempotency_key)
        if existing_by_key is not None:
            if (
                existing_by_key.financing_application_id != application_id
                or existing_by_key.recipient_account != recipient_account
            ):
                raise DuplicateDisbursementError(
                    f"Idempotency key '{idempotency_key}' was previously used "
                    f"for a different application or recipient"
                )
            return existing_by_key

        # 2. Verify application existence with row-level lock
        application = self._financing_repo.get_by_id(application_id, for_update=True)
        if application is None:
            raise FinancingApplicationNotFoundError(f"Application {application_id} not found")

        # 3. Duplicate check on application
        existing_by_app = self._disbursement_repo.get_by_application_id(application_id)
        if existing_by_app is not None or application.status == FinancingStatus.DISBURSED.value:
            raise DuplicateDisbursementError(
                f"Application {application_id} has already been disbursed"
            )

        # 4. State validation: Only APPROVED applications can be disbursed
        if application.status != FinancingStatus.APPROVED.value:
            raise InvalidDisbursementStateError(
                f"Cannot disburse application in '{application.status}' status"
            )

        # 5. Financial amount validation
        net_amount = application.net_disbursement_amount
        approved_amount = application.approved_amount
        fee_amount = application.fee_amount
        if net_amount is None or approved_amount is None or fee_amount is None:
            raise InvalidDisbursementStateError(
                "Application financial amounts are not finalized for disbursement"
            )

        # 6. Call payment rails provider
        provider_req = DisbursementRequest(
            application_id=application_id,
            amount=net_amount,
            recipient_account=recipient_account,
            idempotency_key=idempotency_key,
        )
        try:
            provider_result = self._provider.disburse(provider_req)
        except Exception as exc:
            err_msg = f"Disbursement provider connection failure: {exc}"
            self._audit_repo.create(
                FinancingAuditLog(
                    application_id=application_id,
                    from_status=application.status,
                    to_status=application.status,
                    actor="DISBURSEMENT_GATEWAY",
                    correlation_id=corr_id,
                    reason=err_msg,
                )
            )
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise DisbursementExecutionError(err_msg) from exc

        # 7. Handle provider failure / timeout
        if provider_result.status in (DisbursementStatus.FAILED, DisbursementStatus.TIMEOUT):
            err_msg = provider_result.error_message or "Disbursement provider rejected transfer"
            self._audit_repo.create(
                FinancingAuditLog(
                    application_id=application_id,
                    from_status=application.status,
                    to_status=application.status,
                    actor="DISBURSEMENT_GATEWAY",
                    correlation_id=corr_id,
                    reason=f"Disbursement failed: {err_msg}",
                )
            )
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise DisbursementExecutionError(err_msg)

        # 8. Create completed Disbursement record
        disbursement = Disbursement(
            financing_application_id=application_id,
            idempotency_key=idempotency_key,
            amount=net_amount,
            recipient_account=recipient_account,
            status=DisbursementStatus.COMPLETED.value,
            provider_transaction_id=provider_result.provider_transaction_id,
            disbursed_at=provider_result.disbursed_at,
        )

        try:
            self._disbursement_repo.create(disbursement)

            # 9. Transition application lifecycle to DISBURSED
            application.status = FinancingStatus.DISBURSED.value

            # 10. Transition underlying invoice lifecycle to FINANCED
            invoice = self._invoice_repo.get_by_id(application.invoice_id)
            if invoice is not None:
                invoice.status = InvoiceStatus.FINANCED.value

            # 11. Post immutable double-entry ledger journal transaction with reserve recognition
            receivable_amount = application.requested_amount
            reserve_amount = receivable_amount - approved_amount
            self._ledger_service.post_disbursement_transaction(
                application_id=application_id,
                receivable_amount=receivable_amount,
                reserve_amount=reserve_amount,
                fee_amount=fee_amount,
                net_amount=net_amount,
            )

            # 12. Record audit log entry
            self._audit_repo.create(
                FinancingAuditLog(
                    application_id=application_id,
                    from_status=FinancingStatus.APPROVED.value,
                    to_status=FinancingStatus.DISBURSED.value,
                    actor="DISBURSEMENT_SERVICE",
                    correlation_id=corr_id,
                    reason=(
                        f"Disbursed {net_amount} to {recipient_account} "
                        f"via provider tx {provider_result.provider_transaction_id}"
                    ),
                )
            )

            # 13. Atomic commit of entire disbursement, state transitions, ledger, and audit log
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            err_str = str(exc).lower()
            if (
                "ix_disbursements_idempotency_key" in err_str
                or "ix_disbursements_financing_application_id" in err_str
                or "unique constraint" in err_str
            ):
                raise DuplicateDisbursementError(
                    f"Disbursement conflict for application {application_id}"
                ) from exc
            raise
        except Exception:
            self._session.rollback()
            raise

        return disbursement

    def get_disbursement(self, disbursement_id: uuid.UUID) -> Disbursement | None:
        """Retrieve disbursement by ID."""
        return self._disbursement_repo.get_by_id(disbursement_id)

    def get_disbursement_by_application(self, application_id: uuid.UUID) -> Disbursement | None:
        """Retrieve disbursement by financing application ID."""
        return self._disbursement_repo.get_by_application_id(application_id)


def get_disbursement_service(
    session: Session = Depends(get_db),
    ledger_service: LedgerService = Depends(get_ledger_service),
) -> DisbursementService:
    """FastAPI dependency provider injecting repositories and services into DisbursementService."""
    disbursement_repo = DisbursementRepository(session)
    financing_repo = FinancingRepository(session)
    invoice_repo = InvoiceRepository(session)
    audit_repo = AuditRepository(session)
    provider = SimulatedDisbursementProvider()
    return DisbursementService(
        session=session,
        disbursement_repo=disbursement_repo,
        financing_repo=financing_repo,
        invoice_repo=invoice_repo,
        ledger_service=ledger_service,
        provider=provider,
        audit_repo=audit_repo,
    )
