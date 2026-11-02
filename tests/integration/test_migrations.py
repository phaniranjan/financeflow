import pytest
from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy import inspect

from financeflow.db.base import Base
from financeflow.db.session import engine


@pytest.fixture
def alembic_config():
    """Create Alembic Config pointing to alembic.ini."""
    cfg = Config("alembic.ini")
    return cfg


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure database is in a clean state and alembic_version is reset."""
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE;"))
        conn.commit()
    yield
    # Clean up after test
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as conn:
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

        # 1. Upgrade to head
        command.upgrade(alembic_config, "head")

        inspector = inspect(engine)
        upgraded_tables = set(inspector.get_table_names())
        assert "businesses" in upgraded_tables
        assert "invoices" in upgraded_tables

        # 2. Verify column specifications and constraints
        invoice_columns = {col["name"]: col for col in inspector.get_columns("invoices")}
        assert "amount" in invoice_columns
        amount_type = invoice_columns["amount"]["type"]
        assert isinstance(amount_type, sa.Numeric)
        assert amount_type.precision == 19
        assert amount_type.scale == 2

        # 3. Clean up / Downgrade back to base
        command.downgrade(alembic_config, "base")
        inspector = inspect(engine)
        downgraded_tables = set(inspector.get_table_names())
        assert "invoices" not in downgraded_tables
        assert "businesses" not in downgraded_tables

        # 4. Re-upgrade to head to verify repeatable migration application
        command.upgrade(alembic_config, "head")
        inspector = inspect(engine)
        reupgraded_tables = set(inspector.get_table_names())
        assert "invoices" in reupgraded_tables
        assert "businesses" in reupgraded_tables
