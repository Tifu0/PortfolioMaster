"""Add server default to market_quotes status

Revision ID: 2a8b9c0d1e2f
Revises: 1756f565959b
Create Date: 2026-10-24 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a8b9c0d1e2f'
down_revision: Union[str, Sequence[str], None] = '1756f565959b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set server default for market_quotes status column."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE IF EXISTS public.market_quotes ALTER COLUMN status SET DEFAULT 'UNAVAILABLE';")
    else:
        with op.batch_alter_table('market_quotes') as batch_op:
            batch_op.alter_column('status', server_default='UNAVAILABLE')


def downgrade() -> None:
    """Remove server default for market_quotes status column."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE IF EXISTS public.market_quotes ALTER COLUMN status DROP DEFAULT;")
    else:
        with op.batch_alter_table('market_quotes') as batch_op:
            batch_op.alter_column('status', server_default=None)
