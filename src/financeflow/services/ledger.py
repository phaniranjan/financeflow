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
        receivable_amount: Decimal,
        reserve_amount: Decimal,
        fee_amount: Decimal,
        net_amount: Decimal,
    ) -> LedgerTransaction:
        """Post a balanced transaction recognizing receivables, reserve, fee, and cash."""
        # Enforce fundamental double-entry balance invariant: Debits == Credits
        if receivable_amount != (reserve_amount + fee_amount + net_amount):
            raise LedgerImbalanceError(
                f"Ledger imbalance: receivable ({receivable_amount}) != "
                f"reserve ({reserve_amount}) + fee ({fee_amount}) + net ({net_amount})"
            )

        accounts = self.ensure_standard_accounts()
        rec_acc = accounts[RECEIVABLES_ACCOUNT_NUMBER]
        res_acc = accounts[RESERVE_PAYABLE_ACCOUNT_NUMBER]
        fee_acc = accounts[FEE_REVENUE_ACCOUNT_NUMBER]
        cash_acc = accounts[CASH_ACCOUNT_NUMBER]

        tx = self._ledger_repo.create_transaction(
            LedgerTransaction(
                transaction_type="FINANCING_DISBURSEMENT",
                reference_id=application_id,
                description=f"Disbursement for financing application {application_id}",
            )
        )

        # 1. Debit: Receivables asset increases by gross receivable amount
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=rec_acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=receivable_amount,
            )
        )

        # 2. Credit: Reserve payable liability owed to business
        if reserve_amount > Decimal("0.00"):
            self._ledger_repo.create_entry(
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=res_acc.id,
                    entry_type=EntryType.CREDIT.value,
                    amount=reserve_amount,
                )
            )

        # 3. Credit: Fee revenue increases by financing fee
        if fee_amount > Decimal("0.00"):
            self._ledger_repo.create_entry(
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=fee_acc.id,
                    entry_type=EntryType.CREDIT.value,
                    amount=fee_amount,
                )
            )

        # 4. Credit: Cash asset decreases by net disbursement payout
        if net_amount > Decimal("0.00"):
            self._ledger_repo.create_entry(
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=cash_acc.id,
                    entry_type=EntryType.CREDIT.value,
                    amount=net_amount,
                )
            )

        return tx

    def post_settlement_transaction(
        self,
        application_id: uuid.UUID,
        repayment_amount: Decimal,
    ) -> LedgerTransaction:
        """Post a balanced 2-legged double-entry transaction for debtor collection."""
        if repayment_amount <= Decimal("0.00"):
            raise LedgerImbalanceError(
                f"Ledger imbalance: repayment amount must be positive, got {repayment_amount}"
            )

        accounts = self.ensure_standard_accounts()
        cash_acc = accounts[CASH_ACCOUNT_NUMBER]
        rec_acc = accounts[RECEIVABLES_ACCOUNT_NUMBER]

        tx = self._ledger_repo.create_transaction(
            LedgerTransaction(
                transaction_type="FINANCING_SETTLEMENT",
                reference_id=application_id,
                description=f"Debtor settlement for financing application {application_id}",
            )
        )

        # 1. Debit Cash: Cash asset increases by debtor collection
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=cash_acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=repayment_amount,
            )
        )

        # 2. Credit Factoring Receivables: Extinguish factoring receivable
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=rec_acc.id,
                entry_type=EntryType.CREDIT.value,
                amount=repayment_amount,
            )
        )

        return tx

    def post_reserve_release_transaction(
        self,
        application_id: uuid.UUID,
        reserve_amount: Decimal,
        settlement_fee: Decimal,
        net_refund_amount: Decimal,
    ) -> LedgerTransaction:
        """Post a balanced double-entry transaction releasing reserve to the client business."""
        if reserve_amount != (settlement_fee + net_refund_amount):
            raise LedgerImbalanceError(
                f"Ledger imbalance: reserve ({reserve_amount}) != "
                f"fee ({settlement_fee}) + net refund ({net_refund_amount})"
            )

        accounts = self.ensure_standard_accounts()
        cash_acc = accounts[CASH_ACCOUNT_NUMBER]
        res_acc = accounts[RESERVE_PAYABLE_ACCOUNT_NUMBER]
        fee_acc = accounts[FEE_REVENUE_ACCOUNT_NUMBER]

        tx = self._ledger_repo.create_transaction(
            LedgerTransaction(
                transaction_type="RESERVE_RELEASE",
                reference_id=application_id,
                description=f"Reserve release refund for financing application {application_id}",
            )
        )

        # 1. Debit Customer Reserve Payable: Extinguish reserve liability
        self._ledger_repo.create_entry(
            LedgerEntry(
                transaction_id=tx.id,
                account_id=res_acc.id,
                entry_type=EntryType.DEBIT.value,
                amount=reserve_amount,
            )
        )

        # 2. Credit Fee Revenue: Recognize settlement fee if any
        if settlement_fee > Decimal("0.00"):
            self._ledger_repo.create_entry(
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=fee_acc.id,
                    entry_type=EntryType.CREDIT.value,
                    amount=settlement_fee,
                )
            )

        # 3. Credit Cash: Cash asset decreases by payout to client business
        if net_refund_amount > Decimal("0.00"):
            self._ledger_repo.create_entry(
                LedgerEntry(
                    transaction_id=tx.id,
                    account_id=cash_acc.id,
                    entry_type=EntryType.CREDIT.value,
                    amount=net_refund_amount,
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
