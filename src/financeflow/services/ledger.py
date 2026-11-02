import uuid
from decimal import Decimal
from typing import Any

from fastapi import Depends
from sqlalchemy.orm import Session

from financeflow.core.exceptions import (
    LedgerAccountNotFoundError,
    LedgerImbalanceError,
)
from financeflow.db.session import get_db
from financeflow.models.ledger import (
    AccountType,
    EntryType,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from financeflow.repositories.ledger import LedgerRepository

# Standard chart of accounts identifiers
CASH_ACCOUNT_NUMBER = "1010"
RECEIVABLES_ACCOUNT_NUMBER = "1200"
RESERVE_PAYABLE_ACCOUNT_NUMBER = "2100"
FEE_REVENUE_ACCOUNT_NUMBER = "4010"


class LedgerService:
    """Domain service managing double-entry bookkeeping, postings, and balance reconciliation."""

    def __init__(self, session: Session, ledger_repo: LedgerRepository) -> None:
        self._session = session
        self._ledger_repo = ledger_repo

    def ensure_standard_accounts(self) -> dict[str, LedgerAccount]:
        """Ensure standard chart of accounts exists in the ledger."""
        standards = [
            (CASH_ACCOUNT_NUMBER, "Operating Cash", AccountType.ASSET.value),
            (RECEIVABLES_ACCOUNT_NUMBER, "Factoring Receivables", AccountType.ASSET.value),
            (
                RESERVE_PAYABLE_ACCOUNT_NUMBER,
                "Customer Reserve Payable",
                AccountType.LIABILITY.value,
            ),
            (FEE_REVENUE_ACCOUNT_NUMBER, "Financing Fee Revenue", AccountType.REVENUE.value),
        ]
        accounts: dict[str, LedgerAccount] = {}
        for num, name, acc_type in standards:
            acc = self._ledger_repo.get_account_by_number(num)
            if acc is None:
                acc = self._ledger_repo.create_account(
                    LedgerAccount(account_number=num, name=name, account_type=acc_type)
                )
            accounts[num] = acc
        return accounts

    def post_disbursement_transaction(
        self,
        application_id: uuid.UUID,
        approved_amount: Decimal,
        fee_amount: Decimal,
        net_amount: Decimal,
    ) -> LedgerTransaction:
        """Post a balanced 3-legged double-entry transaction for a financing disbursement."""
        # Enforce fundamental double-entry balance invariant: Debits == Credits
        if approved_amount != (fee_amount + net_amount):
            raise LedgerImbalanceError(
                f"Ledger imbalance: approved ({approved_amount}) != "
                f"fee ({fee_amount}) + net ({net_amount})"
            )

        accounts = self.ensure_standard_accounts()
        rec_acc = accounts[RECEIVABLES_ACCOUNT_NUMBER]
        fee_acc = accounts[FEE_REVENUE_ACCOUNT_NUMBER]
        cash_acc = accounts[CASH_ACCOUNT_NUMBER]

        tx = self._ledger_repo.create_transaction(
            LedgerTransaction(
                transaction_type="FINANCING_DISBURSEMENT",
                reference_id=application_id,
                description=f"Disbursement for financing application {application_id}",
            )
        )

        # 1. Debit: Receivables asset increases by approved advance
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=rec_acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=approved_amount,
            )
        )

        # 2. Credit: Fee revenue increases by financing fee
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=fee_acc.id,
                entry_type=EntryType.CREDIT.value,
                amount=fee_amount,
            )
        )

        # 3. Credit: Cash asset decreases by net disbursement payout
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=cash_acc.id,
                entry_type=EntryType.CREDIT.value,
                amount=net_amount,
            )
        )

        return tx

    def get_account_balance(self, account_number: str) -> Decimal:
        """Retrieve balance of a ledger account by account number."""
        acc = self._ledger_repo.get_account_by_number(account_number)
        if acc is None:
            raise LedgerAccountNotFoundError(f"Account {account_number} not found")
        return self._ledger_repo.get_account_balance(acc.id)

    def list_accounts_with_balances(self) -> list[tuple[LedgerAccount, Decimal]]:
        """List all accounts in the chart of accounts along with calculated net balances."""
        self.ensure_standard_accounts()
        accounts = self._ledger_repo.list_accounts()
        return [(acc, self._ledger_repo.get_account_balance(acc.id)) for acc in accounts]

    def reconcile_ledger(self) -> dict[str, Any]:
        """Perform system-wide trial balance reconciliation verifying total debits equal credits."""
        total_debits, total_credits = self._ledger_repo.get_total_ledger_debits_and_credits()
        discrepancy = total_debits - total_credits
        return {
            "is_balanced": discrepancy == Decimal("0.00"),
            "total_debits": total_debits,
            "total_credits": total_credits,
            "discrepancy": discrepancy,
        }


def get_ledger_service(session: Session = Depends(get_db)) -> LedgerService:
    """FastAPI dependency provider injecting LedgerRepository into LedgerService."""
    repo = LedgerRepository(session)
    return LedgerService(session=session, ledger_repo=repo)
