from fastapi import APIRouter, Depends, status

from financeflow.schemas.ledger import (
    LedgerAccountResponse,
    TrialBalanceResponse,
)
from financeflow.services.ledger import (
    LedgerService,
    get_ledger_service,
)

router = APIRouter(prefix="/ledger", tags=["Ledger"])


@router.get(
    "/accounts",
    response_model=list[LedgerAccountResponse],
    status_code=status.HTTP_200_OK,
    summary="List general ledger chart of accounts and current balances",
)
def list_ledger_accounts(
    service: LedgerService = Depends(get_ledger_service),
) -> list[LedgerAccountResponse]:
    """Retrieve chart of accounts with up-to-date calculated balances."""
    accounts_with_balances = service.list_accounts_with_balances()
    responses: list[LedgerAccountResponse] = []
    for acc, balance in accounts_with_balances:
        resp = LedgerAccountResponse(
            id=acc.id,
            account_number=acc.account_number,
            name=acc.name,
            account_type=acc.account_type,
            balance=balance,
            created_at=acc.created_at,
        )
        responses.append(resp)
    return responses


@router.get(
    "/reconciliation",
    response_model=TrialBalanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Audit trial balance equality across all debit and credit journal entries",
)
def reconcile_ledger(
    service: LedgerService = Depends(get_ledger_service),
) -> TrialBalanceResponse:
    """Audit the general ledger trial balance ensuring total debits equal total credits."""
    result = service.reconcile_ledger()
    return TrialBalanceResponse(
        is_balanced=result["is_balanced"],
        total_debits=result["total_debits"],
        total_credits=result["total_credits"],
        discrepancy=result["discrepancy"],
    )
