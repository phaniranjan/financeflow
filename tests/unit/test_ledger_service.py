import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from financeflow.core.exceptions import (
    LedgerAccountNotFoundError,
    LedgerImbalanceError,
)
from financeflow.models.ledger import (
    AccountType,
    EntryType,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from financeflow.services.ledger import (
    CASH_ACCOUNT_NUMBER,
    FEE_REVENUE_ACCOUNT_NUMBER,
    RECEIVABLES_ACCOUNT_NUMBER,
    RESERVE_PAYABLE_ACCOUNT_NUMBER,
    LedgerService,
    get_ledger_service,
)


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy Session."""
    return MagicMock()


@pytest.fixture
def mock_ledger_repo():
    """Mock LedgerRepository."""
    return MagicMock()


@pytest.fixture
def ledger_service(mock_session, mock_ledger_repo):
    """LedgerService instance with mocked dependencies."""
    return LedgerService(session=mock_session, ledger_repo=mock_ledger_repo)


class TestEnsureStandardAccounts:
    """Unit tests for LedgerService.ensure_standard_accounts."""

    @pytest.mark.unit
    def test_creates_missing_accounts(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """When accounts do not exist, they are created in the chart of accounts."""
        mock_ledger_repo.get_account_by_number.return_value = None

        def side_effect_create(account: LedgerAccount) -> LedgerAccount:
            account.id = uuid.uuid4()
            return account

        mock_ledger_repo.create_account.side_effect = side_effect_create

        accounts = ledger_service.ensure_standard_accounts()

        assert len(accounts) == 4
        assert CASH_ACCOUNT_NUMBER in accounts
        assert RECEIVABLES_ACCOUNT_NUMBER in accounts
        assert RESERVE_PAYABLE_ACCOUNT_NUMBER in accounts
        assert FEE_REVENUE_ACCOUNT_NUMBER in accounts
        assert mock_ledger_repo.create_account.call_count == 4

    @pytest.mark.unit
    def test_reuses_existing_accounts(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """When accounts already exist, they are retrieved and reused."""
        existing_acc = LedgerAccount(
            id=uuid.uuid4(),
            account_number=CASH_ACCOUNT_NUMBER,
            name="Operating Cash",
            account_type=AccountType.ASSET.value,
        )
        mock_ledger_repo.get_account_by_number.return_value = existing_acc

        accounts = ledger_service.ensure_standard_accounts()

        assert len(accounts) == 4
        assert mock_ledger_repo.create_account.call_count == 0


class TestPostDisbursementTransaction:
    """Unit tests for LedgerService.post_disbursement_transaction."""

    @pytest.mark.unit
    def test_post_disbursement_transaction_success(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Verify balanced 3-legged double-entry transaction posting."""
        app_id = uuid.uuid4()
        receivable = Decimal("50000.00")
        reserve = Decimal("10000.00")
        fee = Decimal("1200.00")
        net = Decimal("38800.00")

        # Mock standard accounts
        acc_cash = LedgerAccount(
            id=uuid.uuid4(),
            account_number=CASH_ACCOUNT_NUMBER,
            name="Cash",
            account_type=AccountType.ASSET.value,
        )
        acc_rec = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RECEIVABLES_ACCOUNT_NUMBER,
            name="Receivables",
            account_type=AccountType.ASSET.value,
        )
        acc_fee = LedgerAccount(
            id=uuid.uuid4(),
            account_number=FEE_REVENUE_ACCOUNT_NUMBER,
            name="Fee Revenue",
            account_type=AccountType.REVENUE.value,
        )
        acc_reserve = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RESERVE_PAYABLE_ACCOUNT_NUMBER,
            name="Reserve",
            account_type=AccountType.LIABILITY.value,
        )

        def mock_get_acc(num: str):
            mapping = {
                CASH_ACCOUNT_NUMBER: acc_cash,
                RECEIVABLES_ACCOUNT_NUMBER: acc_rec,
                RESERVE_PAYABLE_ACCOUNT_NUMBER: acc_reserve,
                FEE_REVENUE_ACCOUNT_NUMBER: acc_fee,
            }
            return mapping.get(num)

        mock_ledger_repo.get_account_by_number.side_effect = mock_get_acc

        def mock_create_tx(tx: LedgerTransaction) -> LedgerTransaction:
            tx.id = uuid.uuid4()
            return tx

        mock_ledger_repo.create_transaction.side_effect = mock_create_tx

        created_entries = []

        def mock_create_entry(entry: LedgerEntry) -> LedgerEntry:
            entry.id = uuid.uuid4()
            created_entries.append(entry)
            return entry

        mock_ledger_repo.create_entry.side_effect = mock_create_entry

        tx = ledger_service.post_disbursement_transaction(
            application_id=app_id,
            receivable_amount=receivable,
            reserve_amount=reserve,
            fee_amount=fee,
            net_amount=net,
        )

        assert tx is not None
        assert tx.transaction_type == "FINANCING_DISBURSEMENT"
        assert tx.reference_id == app_id
        assert len(created_entries) == 4

        # 1. Debit Receivables
        debit_entry = next(e for e in created_entries if e.entry_type == EntryType.DEBIT.value)
        assert debit_entry.account_id == acc_rec.id
        assert debit_entry.amount == receivable

        # 2. Credit Reserve Payable
        reserve_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_reserve.id and e.entry_type == EntryType.CREDIT.value
        )
        assert reserve_entry.amount == reserve

        # 3. Credit Fee Revenue
        fee_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_fee.id and e.entry_type == EntryType.CREDIT.value
        )
        assert fee_entry.amount == fee

        # 4. Credit Cash
        cash_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_cash.id and e.entry_type == EntryType.CREDIT.value
        )
        assert cash_entry.amount == net

    @pytest.mark.unit
    def test_post_disbursement_transaction_imbalance_raises(
        self, ledger_service: LedgerService
    ) -> None:
        """Posting an imbalanced transaction raises LedgerImbalanceError."""
        app_id = uuid.uuid4()
        receivable = Decimal("50000.00")
        reserve = Decimal("10000.00")
        fee = Decimal("1200.00")
        net = Decimal("35000.00")  # Imbalanced: 50000 != 10000 + 1200 + 35000 (46200)

        with pytest.raises(LedgerImbalanceError) as exc_info:
            ledger_service.post_disbursement_transaction(
                application_id=app_id,
                receivable_amount=receivable,
                reserve_amount=reserve,
                fee_amount=fee,
                net_amount=net,
            )
        assert "Ledger imbalance" in str(exc_info.value)


class TestPostSettlementTransaction:
    """Unit tests for LedgerService.post_settlement_transaction."""

    @pytest.mark.unit
    def test_post_settlement_transaction_success(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Verify balanced debtor repayment transaction posting."""
        app_id = uuid.uuid4()
        repayment = Decimal("50000.00")

        acc_cash = LedgerAccount(
            id=uuid.uuid4(),
            account_number=CASH_ACCOUNT_NUMBER,
            name="Cash",
            account_type=AccountType.ASSET.value,
        )
        acc_rec = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RECEIVABLES_ACCOUNT_NUMBER,
            name="Receivables",
            account_type=AccountType.ASSET.value,
        )
        acc_reserve = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RESERVE_PAYABLE_ACCOUNT_NUMBER,
            name="Reserve Payable",
            account_type=AccountType.LIABILITY.value,
        )

        def mock_get_acc(num: str):
            mapping = {
                CASH_ACCOUNT_NUMBER: acc_cash,
                RECEIVABLES_ACCOUNT_NUMBER: acc_rec,
                RESERVE_PAYABLE_ACCOUNT_NUMBER: acc_reserve,
            }
            return mapping.get(num)

        mock_ledger_repo.get_account_by_number.side_effect = mock_get_acc

        def mock_create_tx(tx: LedgerTransaction) -> LedgerTransaction:
            tx.id = uuid.uuid4()
            return tx

        mock_ledger_repo.create_transaction.side_effect = mock_create_tx

        created_entries = []

        def mock_create_entry(entry: LedgerEntry) -> LedgerEntry:
            entry.id = uuid.uuid4()
            created_entries.append(entry)
            return entry

        mock_ledger_repo.create_entry.side_effect = mock_create_entry

        tx = ledger_service.post_settlement_transaction(
            application_id=app_id,
            repayment_amount=repayment,
        )

        assert tx is not None
        assert tx.transaction_type == "FINANCING_SETTLEMENT"
        assert tx.reference_id == app_id
        assert len(created_entries) == 2

        # 1. Debit Cash
        debit_entry = next(e for e in created_entries if e.entry_type == EntryType.DEBIT.value)
        assert debit_entry.account_id == acc_cash.id
        assert debit_entry.amount == repayment

        # 2. Credit Receivables
        rec_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_rec.id and e.entry_type == EntryType.CREDIT.value
        )
        assert rec_entry.amount == repayment

    @pytest.mark.unit
    def test_post_settlement_transaction_imbalance_raises(
        self, ledger_service: LedgerService
    ) -> None:
        """Raises LedgerImbalanceError if repayment amount is non-positive."""
        app_id = uuid.uuid4()
        with pytest.raises(LedgerImbalanceError):
            ledger_service.post_settlement_transaction(
                application_id=app_id,
                repayment_amount=Decimal("0.00"),
            )


class TestPostReserveReleaseTransaction:
    """Unit tests for LedgerService.post_reserve_release_transaction."""

    @pytest.mark.unit
    def test_post_reserve_release_success(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Verify balanced reserve release payout to business."""
        app_id = uuid.uuid4()
        reserve = Decimal("10000.00")
        fee = Decimal("100.00")
        net_refund = Decimal("9900.00")

        acc_cash = LedgerAccount(
            id=uuid.uuid4(),
            account_number=CASH_ACCOUNT_NUMBER,
            name="Cash",
            account_type=AccountType.ASSET.value,
        )
        acc_fee = LedgerAccount(
            id=uuid.uuid4(),
            account_number=FEE_REVENUE_ACCOUNT_NUMBER,
            name="Fee Revenue",
            account_type=AccountType.REVENUE.value,
        )
        acc_reserve = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RESERVE_PAYABLE_ACCOUNT_NUMBER,
            name="Reserve Payable",
            account_type=AccountType.LIABILITY.value,
        )

        def mock_get_acc(num: str):
            mapping = {
                CASH_ACCOUNT_NUMBER: acc_cash,
                FEE_REVENUE_ACCOUNT_NUMBER: acc_fee,
                RESERVE_PAYABLE_ACCOUNT_NUMBER: acc_reserve,
            }
            return mapping.get(num)

        mock_ledger_repo.get_account_by_number.side_effect = mock_get_acc

        def mock_create_tx(tx: LedgerTransaction) -> LedgerTransaction:
            tx.id = uuid.uuid4()
            return tx

        mock_ledger_repo.create_transaction.side_effect = mock_create_tx

        created_entries = []

        def mock_create_entry(entry: LedgerEntry) -> LedgerEntry:
            entry.id = uuid.uuid4()
            created_entries.append(entry)
            return entry

        mock_ledger_repo.create_entry.side_effect = mock_create_entry

        tx = ledger_service.post_reserve_release_transaction(
            application_id=app_id,
            reserve_amount=reserve,
            settlement_fee=fee,
            net_refund_amount=net_refund,
        )

        assert tx is not None
        assert tx.transaction_type == "RESERVE_RELEASE"
        assert tx.reference_id == app_id
        assert len(created_entries) == 3

        # 1. Debit Reserve Payable
        debit_entry = next(e for e in created_entries if e.entry_type == EntryType.DEBIT.value)
        assert debit_entry.account_id == acc_reserve.id
        assert debit_entry.amount == reserve

        # 2. Credit Fee Revenue
        fee_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_fee.id and e.entry_type == EntryType.CREDIT.value
        )
        assert fee_entry.amount == fee

        # 3. Credit Cash
        cash_entry = next(
            e
            for e in created_entries
            if e.account_id == acc_cash.id and e.entry_type == EntryType.CREDIT.value
        )
        assert cash_entry.amount == net_refund

    @pytest.mark.unit
    def test_post_reserve_release_zero_fee(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Verify reserve release with 0 fee creates only 2 entries (debit reserve, credit cash)."""
        app_id = uuid.uuid4()
        reserve = Decimal("10000.00")
        fee = Decimal("0.00")
        net_refund = Decimal("10000.00")

        acc_cash = LedgerAccount(
            id=uuid.uuid4(),
            account_number=CASH_ACCOUNT_NUMBER,
            name="Cash",
            account_type=AccountType.ASSET.value,
        )
        acc_reserve = LedgerAccount(
            id=uuid.uuid4(),
            account_number=RESERVE_PAYABLE_ACCOUNT_NUMBER,
            name="Reserve Payable",
            account_type=AccountType.LIABILITY.value,
        )

        def mock_get_acc(num: str):
            mapping = {
                CASH_ACCOUNT_NUMBER: acc_cash,
                RESERVE_PAYABLE_ACCOUNT_NUMBER: acc_reserve,
            }
            return mapping.get(num)

        mock_ledger_repo.get_account_by_number.side_effect = mock_get_acc

        def mock_create_tx(tx: LedgerTransaction) -> LedgerTransaction:
            tx.id = uuid.uuid4()
            return tx

        mock_ledger_repo.create_transaction.side_effect = mock_create_tx

        created_entries = []

        def mock_create_entry(entry: LedgerEntry) -> LedgerEntry:
            entry.id = uuid.uuid4()
            created_entries.append(entry)
            return entry

        mock_ledger_repo.create_entry.side_effect = mock_create_entry

        tx = ledger_service.post_reserve_release_transaction(
            application_id=app_id,
            reserve_amount=reserve,
            settlement_fee=fee,
            net_refund_amount=net_refund,
        )

        assert tx is not None
        assert len(created_entries) == 2

    @pytest.mark.unit
    def test_post_reserve_release_imbalance_raises(self, ledger_service: LedgerService) -> None:
        """Raises LedgerImbalanceError if reserve != fee + net_refund."""
        app_id = uuid.uuid4()
        with pytest.raises(LedgerImbalanceError):
            ledger_service.post_reserve_release_transaction(
                application_id=app_id,
                reserve_amount=Decimal("10000.00"),
                settlement_fee=Decimal("100.00"),
                net_refund_amount=Decimal("9500.00"),  # Imbalanced
            )


class TestGetAccountBalance:
    """Unit tests for LedgerService.get_account_balance."""

    @pytest.mark.unit
    def test_get_balance_success(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Retrieves balance for existing account."""
        acc_id = uuid.uuid4()
        acc = LedgerAccount(
            id=acc_id,
            account_number=CASH_ACCOUNT_NUMBER,
            name="Cash",
            account_type=AccountType.ASSET.value,
        )
        mock_ledger_repo.get_account_by_number.return_value = acc
        mock_ledger_repo.get_account_balance.return_value = Decimal("50000.00")

        balance = ledger_service.get_account_balance(CASH_ACCOUNT_NUMBER)
        assert balance == Decimal("50000.00")
        mock_ledger_repo.get_account_balance.assert_called_once_with(acc_id)

    @pytest.mark.unit
    def test_get_balance_account_not_found_raises(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Raises LedgerAccountNotFoundError when account number does not exist."""
        mock_ledger_repo.get_account_by_number.return_value = None

        with pytest.raises(LedgerAccountNotFoundError) as exc_info:
            ledger_service.get_account_balance("9999")
        assert "Account 9999 not found" in str(exc_info.value)


class TestReconcileLedger:
    """Unit tests for LedgerService.reconcile_ledger."""

    @pytest.mark.unit
    def test_reconcile_ledger_balanced(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Reconciliation passes when debits equal credits."""
        mock_ledger_repo.get_total_ledger_debits_and_credits.return_value = (
            Decimal("100000.00"),
            Decimal("100000.00"),
        )

        result = ledger_service.reconcile_ledger()
        assert result["is_balanced"] is True
        assert result["total_debits"] == Decimal("100000.00")
        assert result["total_credits"] == Decimal("100000.00")
        assert result["discrepancy"] == Decimal("0.00")

    @pytest.mark.unit
    def test_reconcile_ledger_imbalanced(
        self, ledger_service: LedgerService, mock_ledger_repo: MagicMock
    ) -> None:
        """Reconciliation fails when debits do not equal credits."""
        mock_ledger_repo.get_total_ledger_debits_and_credits.return_value = (
            Decimal("100000.00"),
            Decimal("99500.00"),
        )

        result = ledger_service.reconcile_ledger()
        assert result["is_balanced"] is False
        assert result["total_debits"] == Decimal("100000.00")
        assert result["total_credits"] == Decimal("99500.00")
        assert result["discrepancy"] == Decimal("500.00")


class TestGetLedgerServiceDependency:
    """Unit tests for get_ledger_service dependency injection."""

    @pytest.mark.unit
    def test_get_ledger_service(self, mock_session: MagicMock) -> None:
        """Dependency factory returns LedgerService with injected session and repo."""
        service = get_ledger_service(session=mock_session)
        assert isinstance(service, LedgerService)
        assert service._session == mock_session

    @pytest.mark.unit
    def test_services_init_exports(self) -> None:
        """Verify services package exports all required service classes and providers."""
        import financeflow.services as s

        assert hasattr(s, "DisbursementService")
        assert hasattr(s, "FinancingService")
        assert hasattr(s, "InvoiceService")
        assert hasattr(s, "LedgerService")
        assert hasattr(s, "SettlementService")
        assert hasattr(s, "get_disbursement_service")
        assert hasattr(s, "get_financing_service")
        assert hasattr(s, "get_invoice_service")
        assert hasattr(s, "get_ledger_service")
        assert hasattr(s, "get_settlement_service")
        assert len(s.__all__) == 10
