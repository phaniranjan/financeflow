"""allow_multiple_settlements_and_partial_settlement_status

Revision ID: 5b0236bc62e1
Revises: 4a0125ab51d0
Create Date: 2026-11-03 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b0236bc62e1'
down_revision: Union[str, None] = '4a0125ab51d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Allow multiple settlements for a single financing application
    op.drop_index('ix_settlements_financing_application_id', table_name='settlements')
    op.create_index(
        op.f('ix_settlements_financing_application_id'),
        'settlements',
        ['financing_application_id'],
        unique=False,
    )

    # 2. Update active financing unique index to include PARTIALLY_SETTLED
    op.drop_index('uq_financing_active_invoice', table_name='financing_applications')
    op.create_index(
        'uq_financing_active_invoice',
        'financing_applications',
        ['invoice_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('SUBMITTED', 'APPROVED', 'DISBURSED', 'PARTIALLY_SETTLED')"),
    )


def downgrade() -> None:
    # Revert active financing unique index
    op.drop_index('uq_financing_active_invoice', table_name='financing_applications')
    op.create_index(
        'uq_financing_active_invoice',
        'financing_applications',
        ['invoice_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('SUBMITTED', 'APPROVED', 'DISBURSED')"),
    )

    # Revert to unique settlement index
    op.drop_index(op.f('ix_settlements_financing_application_id'), table_name='settlements')
    op.create_index(
        'ix_settlements_financing_application_id',
        'settlements',
        ['financing_application_id'],
        unique=True,
    )
