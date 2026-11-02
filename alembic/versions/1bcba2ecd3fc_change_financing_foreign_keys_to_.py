"""change_financing_foreign_keys_to_restrict

Revision ID: 1bcba2ecd3fc
Revises: 59c27789522b
Create Date: 2026-11-02 22:57:41.979914

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1bcba2ecd3fc'
down_revision: Union[str, None] = '59c27789522b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('financing_applications_invoice_id_fkey', 'financing_applications', type_='foreignkey')
    op.drop_constraint('financing_applications_business_id_fkey', 'financing_applications', type_='foreignkey')
    op.create_foreign_key(
        'financing_applications_business_id_fkey',
        'financing_applications',
        'businesses',
        ['business_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.create_foreign_key(
        'financing_applications_invoice_id_fkey',
        'financing_applications',
        'invoices',
        ['invoice_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    op.drop_constraint('financing_applications_invoice_id_fkey', 'financing_applications', type_='foreignkey')
    op.drop_constraint('financing_applications_business_id_fkey', 'financing_applications', type_='foreignkey')
    op.create_foreign_key(
        'financing_applications_business_id_fkey',
        'financing_applications',
        'businesses',
        ['business_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'financing_applications_invoice_id_fkey',
        'financing_applications',
        'invoices',
        ['invoice_id'],
        ['id'],
        ondelete='CASCADE',
    )
