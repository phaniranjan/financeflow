import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from financeflow.core.exceptions import InvalidSettlementAmountError
from financeflow.models.financing import FinancingApplication, FinancingStatus
from financeflow.models.invoice import Invoice, InvoiceStatus
from financeflow.models.ledger import (
    EntryType,
    LedgerAccount,
    LedgerEntry,
)
from financeflow.models.settlement import Settlement, SettlementStatus
from financeflow.services.ledger import (
    CASH_ACCOUNT_NUMBER,
    FEE_REVENUE_ACCOUNT_NUMBER,
    RECEIVABLES_ACCOUNT_NUMBER,
    RESERVE_PAYABLE_ACCOUNT_NUMBER,
    LedgerService,
)
from financeflow.services.settlement import SettlementService


class TestReserveRecognitionAtDisbursement:
    """TDD tests verifying Fix 2: Contractual reserve payable recognized at disbursement."""

    @pytest.mark.unit
    def test_post_disbursement_recognizes_contractual_reserve(self) -> None:
        """Disbursement books receivable ($40k), reserve ($8k), fee ($960), and cash ($31,040)."""
        mock_repo = MagicMock()
        mock_session = MagicMock()
        service = LedgerService(session=mock_session, ledger_repo=mock_repo)

        app_id = uuid.uuid4()
        receivable = Decimal("40000.00")
        reserve = Decimal("8000.00")
        fee = Decimal("960.00")
        net = Decimal("31040.00")

        acc_cash = LedgerAccount(id=uuid.uuid4(), account_number=CASH_ACCOUNT_NUMBER)
        acc_rec = LedgerAccount(id=uuid.uuid4(), account_number=RECEIVABLES_ACCOUNT_NUMBER)
        acc_reserve = LedgerAccount(id=uuid.uuid4(), account_number=RESERVE_PAYABLE_ACCOUNT_NUMBER)
        acc_fee = LedgerAccount(id=uuid.uuid4(), account_number=FEE_REVENUE_ACCOUNT_NUMBER)

        mapping = {
            CASH_ACCOUNT_NUMBER: acc_cash,
            RECEIVABLES_ACCOUNT_NUMBER: acc_rec,
            RESERVE_PAYABLE_ACCOUNT_NUMBER: acc_reserve,
            FEE_REVENUE_ACCOUNT_NUMBER: acc_fee,
        }
        mock_repo.get_account_by_number.side_effect = lambda num: mapping.get(num)

        created_entries = []

        def mock_create_entry(entry: LedgerEntry) -> LedgerEntry:
            created_entries.append(entry)
            return entry

        mock_repo.create_entry.side_effect = mock_create_entry
        mock_repo.create_transaction.side_effect = lambda tx: tx

        # In Fix 2: post_disbursement_transaction takes receivable_amount and reserve_amount
        tx = service.post_disbursement_transaction(
            application_id=app_id,
            receivable_amount=receivable,
            reserve_amount=reserve,
            fee_amount=fee,
            net_amount=net,
        )

        assert tx is not None
        assert len(created_entries) == 4

        # 1. Debit Receivables for gross amount
        rec_entry = next(e for e in created_entries if e.account_id == acc_rec.id)
        assert rec_entry.entry_type == EntryType.DEBIT.value
        assert rec_entry.amount == receivable

        # 2. Credit Reserve Payable
        res_entry = next(e for e in created_entries if e.account_id == acc_reserve.id)
        assert res_entry.entry_type == EntryType.CREDIT.value
        assert res_entry.amount == reserve

        # 3. Credit Fee Revenue
        fee_entry = next(e for e in created_entries if e.account_id == acc_fee.id)
        assert fee_entry.entry_type == EntryType.CREDIT.value
        assert fee_entry.amount == fee

        # 4. Credit Operating Cash
        cash_entry = next(e for e in created_entries if e.account_id == acc_cash.id)
        assert cash_entry.entry_type == EntryType.CREDIT.value
        assert cash_entry.amount == net


class TestMultiplePartialCollections:
    """TDD tests verifying Fix 1: Partial collections, PARTIALLY_SETTLED, and final release."""

    @pytest.mark.unit
    def test_partial_collection_transitions_to_partially_settled(self) -> None:
        """First partial payment sets status PARTIALLY_SETTLED while invoice stays FINANCED."""
        mock_session = MagicMock()
        mock_settlement_repo = MagicMock()
        mock_financing_repo = MagicMock()
        mock_invoice_repo = MagicMock()
        mock_ledger_service = MagicMock()
        mock_audit_repo = MagicMock()

        service = SettlementService(
            session=mock_session,
            settlement_repo=mock_settlement_repo,
            financing_repo=mock_financing_repo,
            invoice_repo=mock_invoice_repo,
            ledger_service=mock_ledger_service,
            audit_repo=mock_audit_repo,
        )

        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            invoice_id=inv_id,
            status=FinancingStatus.DISBURSED.value,
            requested_amount=Decimal("40000.00"),
            approved_amount=Decimal("32000.00"),
        )
        invoice = Invoice(id=inv_id, status=InvoiceStatus.FINANCED.value)

        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_invoice_repo.get_by_id.return_value = invoice
        mock_settlement_repo.list_by_application_id.return_value = []
        mock_settlement_repo.create.side_effect = lambda s: s

        # Debtor makes partial payment of $25,000 on $40,000 obligation
        res = service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("25000.00"),
            idempotency_key="idemp-partial-1",
        )

        # Application transitions to PARTIALLY_SETTLED
        assert app.status == FinancingStatus.PARTIALLY_SETTLED.value
        # Invoice remains FINANCED (not PAID)
        assert invoice.status == InvoiceStatus.FINANCED.value
        # Settlement status is SHORTFALL
        assert res.status == SettlementStatus.SHORTFALL.value
        assert res.principal_repaid == Decimal("25000.00")
        assert res.reserve_amount == Decimal("0.00")
        assert res.net_reserve_refunded == Decimal("0.00")

        # Exactly 1 collection ledger transaction posted: $25,000
        mock_ledger_service.post_settlement_transaction.assert_called_once_with(
            application_id=app_id,
            repayment_amount=Decimal("25000.00"),
        )
        # Reserve release transaction NOT called
        mock_ledger_service.post_reserve_release_transaction.assert_not_called()

    @pytest.mark.unit
    def test_final_partial_collection_completes_settlement_and_releases_reserve(self) -> None:
        """Payment 2 of $15k completes $40k total, marking SETTLED and releasing $8k reserve."""
        mock_session = MagicMock()
        mock_settlement_repo = MagicMock()
        mock_financing_repo = MagicMock()
        mock_invoice_repo = MagicMock()
        mock_ledger_service = MagicMock()
        mock_audit_repo = MagicMock()

        service = SettlementService(
            session=mock_session,
            settlement_repo=mock_settlement_repo,
            financing_repo=mock_financing_repo,
            invoice_repo=mock_invoice_repo,
            ledger_service=mock_ledger_service,
            audit_repo=mock_audit_repo,
        )

        app_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            invoice_id=inv_id,
            status=FinancingStatus.PARTIALLY_SETTLED.value,
            requested_amount=Decimal("40000.00"),
            approved_amount=Decimal("32000.00"),
        )
        invoice = Invoice(id=inv_id, status=InvoiceStatus.FINANCED.value)

        # Existing prior settlement of $25,000
        prior_settlement = Settlement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            invoice_id=inv_id,
            repayment_amount=Decimal("25000.00"),
            principal_repaid=Decimal("25000.00"),
            reserve_amount=Decimal("0.00"),
            settlement_fee=Decimal("0.00"),
            net_reserve_refunded=Decimal("0.00"),
            status=SettlementStatus.SHORTFALL.value,
            idempotency_key="idemp-partial-1",
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_invoice_repo.get_by_id.return_value = invoice
        mock_settlement_repo.list_by_application_id.return_value = [prior_settlement]
        mock_settlement_repo.create.side_effect = lambda s: s

        # Debtor pays remaining $15,000 with $100 settlement fee
        res = service.execute_settlement(
            application_id=app_id,
            repayment_amount=Decimal("15000.00"),
            settlement_fee=Decimal("100.00"),
            idempotency_key="idemp-partial-2",
        )

        # Application transitions to SETTLED
        assert app.status == FinancingStatus.SETTLED.value
        # Invoice transitions to PAID
        assert invoice.status == InvoiceStatus.PAID.value
        # Settlement status is COMPLETED
        assert res.status == SettlementStatus.COMPLETED.value
        assert res.principal_repaid == Decimal("7000.00")
        assert res.reserve_amount == Decimal("8000.00")
        assert res.settlement_fee == Decimal("100.00")
        assert res.net_reserve_refunded == Decimal("7900.00")

        # Collection transaction for $15,000
        mock_ledger_service.post_settlement_transaction.assert_called_once_with(
            application_id=app_id,
            repayment_amount=Decimal("15000.00"),
        )
        # Contractual reserve release posted: $8,000 reserve, $100 fee, $7,900 net refund
        mock_ledger_service.post_reserve_release_transaction.assert_called_once_with(
            application_id=app_id,
            reserve_amount=Decimal("8000.00"),
            settlement_fee=Decimal("100.00"),
            net_refund_amount=Decimal("7900.00"),
        )

    @pytest.mark.unit
    def test_overpayment_exceeding_outstanding_receivable_rejected(self) -> None:
        """Repayment exceeding remaining receivable raises InvalidSettlementAmountError."""
        mock_session = MagicMock()
        mock_settlement_repo = MagicMock()
        mock_financing_repo = MagicMock()
        mock_invoice_repo = MagicMock()
        mock_ledger_service = MagicMock()
        mock_audit_repo = MagicMock()

        service = SettlementService(
            session=mock_session,
            settlement_repo=mock_settlement_repo,
            financing_repo=mock_financing_repo,
            invoice_repo=mock_invoice_repo,
            ledger_service=mock_ledger_service,
            audit_repo=mock_audit_repo,
        )

        app_id = uuid.uuid4()
        app = FinancingApplication(
            id=app_id,
            status=FinancingStatus.PARTIALLY_SETTLED.value,
            requested_amount=Decimal("40000.00"),
            approved_amount=Decimal("32000.00"),
        )
        prior = Settlement(
            id=uuid.uuid4(),
            financing_application_id=app_id,
            repayment_amount=Decimal("25000.00"),
        )
        mock_settlement_repo.get_by_idempotency_key.return_value = None
        mock_financing_repo.get_by_id.return_value = app
        mock_settlement_repo.list_by_application_id.return_value = [prior]

        # Remaining is $15,000, attempt to pay $20,000
        with pytest.raises(InvalidSettlementAmountError, match="exceeds outstanding receivable"):
            service.execute_settlement(
                application_id=app_id,
                repayment_amount=Decimal("20000.00"),
                idempotency_key="idemp-overpay",
            )

    @pytest.mark.unit
    def test_financing_application_settlement_property_backward_compatibility(self) -> None:
        """Verify @property settlement returns None when empty and latest when populated."""
        app = FinancingApplication()
        assert app.settlement is None
        s1 = Settlement(id=uuid.uuid4())
        s2 = Settlement(id=uuid.uuid4())
        app.settlements = [s1, s2]
        assert app.settlement is s2
