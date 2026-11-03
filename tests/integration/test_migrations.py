import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import inspect

import financeflow.models  # noqa: F401
from alembic import command
from financeflow.db.session import engine


@pytest.fixture
def alembic_config():
    """Create Alembic Config pointing to alembic.ini."""
    cfg = Config("alembic.ini")
    return cfg


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure database is in a clean state and alembic_version is reset."""
    with engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS settlements CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS financing_audit_logs CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS disbursements CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_entries CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_transactions CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_accounts CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS financing_applications CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS invoices CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS businesses CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
        conn.commit()
    yield
    # Clean up after test
    with engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS settlements CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS financing_audit_logs CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS disbursements CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_entries CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_transactions CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS ledger_accounts CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS financing_applications CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS invoices CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS businesses CASCADE;"))
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
        conn.commit()


class TestDatabaseMigrations:
    """Integration tests verifying Alembic migration application and rollback."""

    @pytest.mark.integration
    def test_migration_upgrade_and_downgrade_lifecycle(self, alembic_config: Config) -> None:
        """Verify upgrade head creates tables, downgrade removes them, and re-upgrade succeeds."""
        inspector = inspect(engine)
        initial_tables = set(inspector.get_table_names())
        assert "businesses" not in initial_tables
        assert "invoices" not in initial_tables
        assert "financing_applications" not in initial_tables

        # 1. Upgrade to head
        command.upgrade(alembic_config, "head")

        inspector = inspect(engine)
        upgraded_tables = set(inspector.get_table_names())
        assert "businesses" in upgraded_tables
        assert "invoices" in upgraded_tables
        assert "financing_applications" in upgraded_tables
        assert "disbursements" in upgraded_tables
        assert "ledger_accounts" in upgraded_tables
        assert "ledger_transactions" in upgraded_tables
        assert "ledger_entries" in upgraded_tables
        assert "financing_audit_logs" in upgraded_tables
        assert "settlements" in upgraded_tables

        # 2. Verify column specifications and constraints
        invoice_columns = {col["name"]: col for col in inspector.get_columns("invoices")}
        assert "amount" in invoice_columns
        amount_type = invoice_columns["amount"]["type"]
        assert isinstance(amount_type, sa.Numeric)
        assert amount_type.precision == 19
        assert amount_type.scale == 2

        financing_columns = {
            col["name"]: col for col in inspector.get_columns("financing_applications")
        }
        assert "requested_amount" in financing_columns
        req_type = financing_columns["requested_amount"]["type"]
        assert isinstance(req_type, sa.Numeric)
        assert req_type.precision == 19
        assert req_type.scale == 2

        # 3. Clean up / Downgrade back to base
        command.downgrade(alembic_config, "base")
        inspector = inspect(engine)
        downgraded_tables = set(inspector.get_table_names())
        assert "settlements" not in downgraded_tables
        assert "financing_audit_logs" not in downgraded_tables
        assert "disbursements" not in downgraded_tables
        assert "ledger_entries" not in downgraded_tables
        assert "ledger_transactions" not in downgraded_tables
        assert "ledger_accounts" not in downgraded_tables
        assert "financing_applications" not in downgraded_tables
        assert "invoices" not in downgraded_tables
        assert "businesses" not in downgraded_tables

        # 4. Re-upgrade to head to verify repeatable migration application
        command.upgrade(alembic_config, "head")
        inspector = inspect(engine)
        reupgraded_tables = set(inspector.get_table_names())
        assert "financing_applications" in reupgraded_tables
        assert "invoices" in reupgraded_tables
        assert "businesses" in reupgraded_tables
