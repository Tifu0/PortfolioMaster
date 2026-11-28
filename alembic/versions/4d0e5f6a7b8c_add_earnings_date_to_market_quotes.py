"""Add earnings_date column to market_quotes and expose it in user_positions_view

Revision ID: 4d0e5f6a7b8c
Revises: 3c9d4e5f6a7b
Create Date: 2026-11-28 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4d0e5f6a7b8c"
down_revision: Union[str, Sequence[str], None] = "3c9d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VIEW_SELECT_COMMON = """
        SELECT
            ui.id,
            ui.user_id,
            ui.user_ticker,
            ui.provider_symbol,
            COALESCE(NULLIF(mq.exchange, 'UNKNOWN'), ui.exchange) AS exchange,
            COALESCE(mq.currency, ui.currency) AS currency,
            COALESCE(ui.company_name, mq.company_name, ui.user_ticker) AS company_name,
            ui.analysis_date,
            ui.analysis_reference_price,
            ui.start_of_year_date,
            ui.start_of_year_price,
            ui.target_price,
            ui.comment,
            ui.active,
            mq.price AS latest_price,
            mq.previous_close,
            mq.quote_timestamp,
            mq.last_valid_fetched_at,
            mq.status AS quote_status,
            mq.error_message AS quote_error,
            CASE
                WHEN mq.price IS NOT NULL AND mq.previous_close IS NOT NULL AND mq.previous_close > 0
                THEN ROUND(((mq.price - mq.previous_close) / mq.previous_close) * 100, 2)
                ELSE NULL
            END AS daily_variation,
            (mq.price IS NOT NULL AND mq.previous_close IS NOT NULL AND mq.previous_close > 0) AS daily_variation_valid,
            CASE
                WHEN mq.price IS NOT NULL AND ui.analysis_reference_price IS NOT NULL AND ui.analysis_reference_price > 0
                THEN ROUND(((mq.price - ui.analysis_reference_price) / ui.analysis_reference_price) * 100, 2)
                ELSE NULL
            END AS variation_since_analysis,
            (mq.price IS NOT NULL AND ui.analysis_reference_price IS NOT NULL AND ui.analysis_reference_price > 0) AS variation_since_analysis_valid,
            CASE
                WHEN mq.price IS NOT NULL AND ui.start_of_year_price IS NOT NULL AND ui.start_of_year_price > 0
                THEN ROUND(((mq.price - ui.start_of_year_price) / ui.start_of_year_price) * 100, 2)
                ELSE NULL
            END AS ytd_variation,
            (mq.price IS NOT NULL AND ui.start_of_year_price IS NOT NULL AND ui.start_of_year_price > 0) AS ytd_variation_valid,
            CASE
                WHEN mq.price IS NOT NULL AND mq.price > 0 AND ui.target_price IS NOT NULL AND ui.target_price > 0
                THEN ROUND(((ui.target_price - mq.price) / mq.price) * 100, 2)
                ELSE NULL
            END AS decline_to_target,
            (mq.price IS NOT NULL AND mq.price > 0 AND ui.target_price IS NOT NULL AND ui.target_price > 0) AS decline_to_target_valid{extra_cols}
        FROM public.user_instruments ui
        LEFT JOIN public.market_quotes mq ON ui.provider_symbol = mq.provider_symbol
"""


def _recreate_user_positions_view(include_earnings_date: bool) -> None:
    extra_cols = ",\n            mq.earnings_date" if include_earnings_date else ""
    select_sql = _VIEW_SELECT_COMMON.format(extra_cols=extra_cols)
    op.execute("DROP VIEW IF EXISTS public.user_positions_view")
    op.execute(
        f"""
        CREATE OR REPLACE VIEW public.user_positions_view
        WITH (security_invoker = true) AS
{select_sql}
        """.strip()
    )
    op.execute("REVOKE ALL ON public.user_positions_view FROM PUBLIC, anon")
    op.execute("GRANT SELECT ON public.user_positions_view TO authenticated, service_role")


def upgrade() -> None:
    """Add nullable earnings_date DATE column to market_quotes across PostgreSQL and SQLite."""
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE public.market_quotes ADD COLUMN IF NOT EXISTS earnings_date DATE")
        _recreate_user_positions_view(include_earnings_date=True)
        return

    inspector = sa.inspect(bind)
    if "market_quotes" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("market_quotes")}
        if "earnings_date" not in existing_cols:
            op.add_column("market_quotes", sa.Column("earnings_date", sa.Date(), nullable=True))


def downgrade() -> None:
    """Remove earnings_date column from market_quotes cleanly."""
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        _recreate_user_positions_view(include_earnings_date=False)
        op.execute("ALTER TABLE public.market_quotes DROP COLUMN IF EXISTS earnings_date")
        return

    inspector = sa.inspect(bind)
    if "market_quotes" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("market_quotes")}
        if "earnings_date" in existing_cols:
            with op.batch_alter_table("market_quotes") as batch_op:
                batch_op.drop_column("earnings_date")
