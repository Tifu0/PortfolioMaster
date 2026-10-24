"""Initial multi-tenant schema with decoupled quotes

Revision ID: 1756f565959b
Revises: 
Create Date: 2026-10-22 14:28:46.686639

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import portfoliomaster.db.schema


# revision identifiers, used by Alembic.
revision: str = '1756f565959b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema safely and idempotently."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'market_quotes' not in existing_tables:
        op.create_table('market_quotes',
            sa.Column('provider_symbol', sa.String(length=50), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False),
            sa.Column('exchange', sa.String(length=50), nullable=False),
            sa.Column('company_name', sa.String(length=255), nullable=True),
            sa.Column('provider', sa.String(length=50), nullable=False),
            sa.Column('price', sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column('previous_close', sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column('quote_timestamp', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_valid_fetched_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('provider_symbol')
        )
        op.create_index('idx_market_quotes_status_attempt', 'market_quotes', ['status', 'last_attempt_at'], unique=False)
        op.create_index('idx_market_quotes_last_attempt', 'market_quotes', ['last_attempt_at'], unique=False)

    if 'refresh_runs' not in existing_tables:
        op.create_table('refresh_runs',
            sa.Column('id', portfoliomaster.db.schema.GUID(length=36), nullable=False),
            sa.Column('user_id', portfoliomaster.db.schema.GUID(length=36), nullable=True),
            sa.Column('trigger_type', sa.String(length=50), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('total_symbols', sa.Integer(), nullable=False),
            sa.Column('processed_symbols', sa.Integer(), nullable=False),
            sa.Column('successful_symbols', sa.Integer(), nullable=False),
            sa.Column('failed_symbols', sa.Integer(), nullable=False),
            sa.Column('current_symbol', sa.String(length=50), nullable=True),
            sa.Column('progress_percent', sa.Numeric(precision=5, scale=2), nullable=False),
            sa.Column('diagnostic_summary', sa.Text(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_refresh_runs_active', 'refresh_runs', ['status', 'started_at'], unique=False)
        op.create_index('idx_refresh_runs_user_started', 'refresh_runs', ['user_id', 'started_at'], unique=False)
        op.create_index(op.f('ix_refresh_runs_status'), 'refresh_runs', ['status'], unique=False)
        op.create_index(op.f('ix_refresh_runs_user_id'), 'refresh_runs', ['user_id'], unique=False)

    if 'user_instruments' not in existing_tables:
        op.create_table('user_instruments',
            sa.Column('id', portfoliomaster.db.schema.GUID(length=36), nullable=False),
            sa.Column('user_id', portfoliomaster.db.schema.GUID(length=36), nullable=False),
            sa.Column('user_ticker', sa.String(length=50), nullable=False),
            sa.Column('provider_symbol', sa.String(length=50), nullable=True),
            sa.Column('exchange', sa.String(length=50), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False),
            sa.Column('company_name', sa.String(length=255), nullable=False),
            sa.Column('analysis_date', sa.Date(), nullable=True),
            sa.Column('analysis_reference_price', sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column('start_of_year_date', sa.Date(), nullable=True),
            sa.Column('start_of_year_price', sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column('target_price', sa.Numeric(precision=18, scale=6), nullable=True),
            sa.Column('comment', sa.Text(), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['provider_symbol'], ['market_quotes.provider_symbol'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'user_ticker', name='uq_user_instruments_tenant_ticker')
        )
        op.create_index('idx_user_instruments_tenant_active', 'user_instruments', ['user_id', 'active'], unique=False)
        op.create_index(op.f('ix_user_instruments_active'), 'user_instruments', ['active'], unique=False)
        op.create_index(op.f('ix_user_instruments_provider_symbol'), 'user_instruments', ['provider_symbol'], unique=False)
        op.create_index(op.f('ix_user_instruments_user_id'), 'user_instruments', ['user_id'], unique=False)

    # Enable RLS if PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE IF EXISTS public.user_instruments ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE IF EXISTS public.market_quotes ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE IF EXISTS public.refresh_runs ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    """Downgrade schema.
    
    WARNING: DESTRUCTIVE OPERATION! Drops user_instruments, refresh_runs, and market_quotes tables.
    Never execute downgrade against a production database without approved backup and operator authorization.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'user_instruments' in existing_tables:
        op.drop_table('user_instruments')
    if 'refresh_runs' in existing_tables:
        op.drop_table('refresh_runs')
    if 'market_quotes' in existing_tables:
        op.drop_table('market_quotes')
