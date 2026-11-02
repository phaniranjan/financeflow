import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from financeflow.models.ledger import (
    AccountType,
    EntryType,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)


class LedgerRepository:
    """Repository handling persistence and balance queries for the double-entry financial ledger."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_account(self, account: LedgerAccount) -> LedgerAccount:
        """Add a new ledger account to chart of accounts and flush."""
        self.session.add(account)
        self.session.flush()
        return account

    def get_account_by_number(self, account_number: str) -> LedgerAccount | None:
        """Find a ledger account by its unique account number."""
        stmt = select(LedgerAccount).where(LedgerAccount.account_number == account_number).limit(1)
        return self.session.scalars(stmt).first()

    def get_account_by_id(self, account_id: uuid.UUID) -> LedgerAccount | None:
        """Find a ledger account by UUID."""
        return self.session.get(LedgerAccount, account_id)

    def list_accounts(self) -> list[LedgerAccount]:
        """List all accounts in the chart of accounts, sorted by account number."""
        stmt = select(LedgerAccount).order_by(LedgerAccount.account_number)
        return list(self.session.scalars(stmt).all())

    def create_transaction(self, transaction: LedgerTransaction) -> LedgerTransaction:
        """Add a new journal transaction to the ledger and flush."""
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def get_transaction_by_id(self, transaction_id: uuid.UUID) -> LedgerTransaction | None:
        """Retrieve a journal transaction by its primary key UUID."""
        return self.session.get(LedgerTransaction, transaction_id)

    def get_transaction_by_reference(self, reference_id: uuid.UUID) -> LedgerTransaction | None:
        """Find journal transaction associated with an operational reference entity."""
        stmt = (
            select(LedgerTransaction).where(LedgerTransaction.reference_id == reference_id).limit(1)
        )
        return self.session.scalars(stmt).first()

    def create_entry(self, entry: LedgerEntry) -> LedgerEntry:
        """Add a debit or credit entry to the ledger and flush."""
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_entries_for_account(self, account_id: uuid.UUID) -> list[LedgerEntry]:
        """Retrieve all debit and credit entries for an account, sorted by creation date."""
        stmt = (
            select(LedgerEntry)
            .where(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.created_at)
        )
        return list(self.session.scalars(stmt).all())

    def get_account_balance(self, account_id: uuid.UUID) -> Decimal:
        """Calculate net balance of an account according to normal balance conventions."""
        account = self.get_account_by_id(account_id)
        if account is None:
            return Decimal("0.00")

        # Sum debits
        debit_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.entry_type == EntryType.DEBIT.value,
        )
        total_debits: Decimal = self.session.scalars(debit_stmt).one()

        # Sum credits
        credit_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.account_id == account_id,
            LedgerEntry.entry_type == EntryType.CREDIT.value,
        )
        total_credits: Decimal = self.session.scalars(credit_stmt).one()

        # ASSET and EXPENSE carry normal debit balances
        if account.account_type in (AccountType.ASSET.value, AccountType.EXPENSE.value):
            return total_debits - total_credits

        # LIABILITY, EQUITY, and REVENUE carry normal credit balances
        return total_credits - total_debits

    def get_total_ledger_debits_and_credits(self) -> tuple[Decimal, Decimal]:
        """Calculate total sum of debits and sum of credits across all entries in the ledger."""
        debit_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.entry_type == EntryType.DEBIT.value
        )
        total_debits: Decimal = self.session.scalars(debit_stmt).one()

        credit_stmt = select(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.00"))).where(
            LedgerEntry.entry_type == EntryType.CREDIT.value
        )
        total_credits: Decimal = self.session.scalars(credit_stmt).one()

        return total_debits, total_credits
