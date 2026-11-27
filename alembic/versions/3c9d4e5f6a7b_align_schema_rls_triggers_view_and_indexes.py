"""Align schema types, constraints, indexes, view, triggers, and hardened RLS

Revision ID: 3c9d4e5f6a7b
Revises: 2a8b9c0d1e2f
Create Date: 2026-11-27 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c9d4e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "2a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_check_if_not_exists(table: str, constraint_name: str, check_sql: str) -> None:
    """Emit an idempotent PostgreSQL DO block adding a CHECK constraint if absent."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{constraint_name}'
                  AND conrelid = 'public.{table}'::regclass
            ) THEN
                ALTER TABLE public.{table}
                    ADD CONSTRAINT {constraint_name} CHECK ({check_sql});
            END IF;
        END
        $$
        """.strip()
    )


def upgrade() -> None:
    """Idempotently align PostgreSQL/SQLite schema, constraints, indexes, view, triggers, and RLS."""
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        # SQLite fallback for local/test schema parity
        op.execute("DROP INDEX IF EXISTS ix_refresh_runs_status")
        op.execute("DROP INDEX IF EXISTS ix_refresh_runs_user_id")
        op.execute("DROP INDEX IF EXISTS ix_user_instruments_user_id")
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_instruments_user_upper_ticker "
            "ON user_instruments (user_id, upper(user_ticker))"
        )
        with op.batch_alter_table("user_instruments") as batch_op:
            batch_op.alter_column("company_name", existing_type=sa.String(length=255), nullable=True)
            batch_op.alter_column("comment", existing_type=sa.Text(), nullable=True)
        return

    # 1. Drop dependent view before altering referenced NUMERIC columns
    op.execute("DROP VIEW IF EXISTS public.user_positions_view")

    # 2. Drop redundant single-column indexes (covered by composite leftmost prefixes) and legacy duplicate CI index
    for idx_name in (
        "ix_refresh_runs_status",
        "ix_refresh_runs_user_id",
        "ix_user_instruments_user_id",
        "idx_user_instruments_user_ticker_ci",
    ):
        op.execute(f"DROP INDEX IF EXISTS public.{idx_name}")

    # 3. Drop legacy SQL_supabase.txt constraints that conflict with tristate PATCH, underscore tickers, or PARTIAL runs
    for tbl, cname in (
        ("user_instruments", "chk_analysis_price_has_date"),
        ("user_instruments", "chk_soy_price_has_date"),
        ("user_instruments", "chk_provider_symbol_format"),
        ("user_instruments", "chk_user_ticker_length"),
        ("market_quotes", "chk_market_quotes_symbol_format"),
        ("market_quotes", "market_quotes_status_check"),
        ("refresh_runs", "refresh_runs_status_check"),
    ):
        op.execute(f"ALTER TABLE public.{tbl} DROP CONSTRAINT IF EXISTS {cname}")

    # 4. Widen financial columns to NUMERIC(20, 6) and align nullability/types
    op.execute(
        """
        ALTER TABLE public.market_quotes
            ALTER COLUMN price TYPE NUMERIC(20, 6),
            ALTER COLUMN previous_close TYPE NUMERIC(20, 6),
            ALTER COLUMN status TYPE VARCHAR(20),
            ALTER COLUMN status SET DEFAULT 'UNAVAILABLE'
        """.strip()
    )
    op.execute(
        """
        ALTER TABLE public.user_instruments
            ALTER COLUMN company_name DROP NOT NULL,
            ALTER COLUMN comment DROP NOT NULL,
            ALTER COLUMN analysis_reference_price TYPE NUMERIC(20, 6),
            ALTER COLUMN start_of_year_price TYPE NUMERIC(20, 6),
            ALTER COLUMN target_price TYPE NUMERIC(20, 6)
        """.strip()
    )

    # 5. Create canonical functional case-insensitive index
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_instruments_user_upper_ticker "
        "ON public.user_instruments (user_id, upper(user_ticker))"
    )

    # 6. Add canonical CHECK constraints idempotently
    _add_check_if_not_exists("market_quotes", "chk_market_quotes_price_pos", "price IS NULL OR price > 0")
    _add_check_if_not_exists(
        "market_quotes", "chk_market_quotes_prev_close_pos", "previous_close IS NULL OR previous_close > 0"
    )
    _add_check_if_not_exists(
        "market_quotes",
        "chk_market_quotes_status",
        "status IN ('FRESH', 'DELAYED', 'STALE', 'UNAVAILABLE', 'ERROR')",
    )
    _add_check_if_not_exists(
        "market_quotes",
        "chk_market_quotes_symbol_format",
        "provider_symbol ~ '^[A-Z0-9._\\-^=/&]{1,50}$'",
    )

    _add_check_if_not_exists(
        "user_instruments",
        "chk_user_instruments_analysis_price_pos",
        "analysis_reference_price IS NULL OR analysis_reference_price > 0",
    )
    _add_check_if_not_exists(
        "user_instruments",
        "chk_user_instruments_soy_price_pos",
        "start_of_year_price IS NULL OR start_of_year_price > 0",
    )
    _add_check_if_not_exists(
        "user_instruments",
        "chk_user_instruments_target_price_pos",
        "target_price IS NULL OR target_price > 0",
    )
    _add_check_if_not_exists(
        "user_instruments",
        "chk_user_ticker_length",
        "length(trim(user_ticker)) >= 1 AND length(trim(user_ticker)) <= 50",
    )
    _add_check_if_not_exists(
        "user_instruments",
        "chk_provider_symbol_format",
        "provider_symbol IS NULL OR provider_symbol ~ '^[A-Z0-9._\\-^=/&]{1,50}$'",
    )

    _add_check_if_not_exists(
        "refresh_runs",
        "chk_refresh_runs_status",
        "status IN ('RUNNING', 'COMPLETED', 'FAILED', 'TIMEOUT', 'PARTIAL')",
    )
    _add_check_if_not_exists(
        "refresh_runs",
        "chk_counts_nonneg",
        "total_symbols >= 0 AND processed_symbols >= 0 AND failed_symbols >= 0 AND successful_symbols >= 0",
    )
    _add_check_if_not_exists(
        "refresh_runs",
        "chk_completed_after_start",
        "completed_at IS NULL OR completed_at >= started_at",
    )

    # 7. Hardened trigger functions (SET search_path = '', schema-qualified refs) and triggers
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
        """.strip()
    )
    op.execute("REVOKE ALL ON FUNCTION public.set_updated_at() FROM PUBLIC, anon, authenticated")

    op.execute("DROP TRIGGER IF EXISTS trg_user_instruments_updated_at ON public.user_instruments")
    op.execute(
        """
        CREATE TRIGGER trg_user_instruments_updated_at
            BEFORE UPDATE ON public.user_instruments
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """.strip()
    )

    op.execute("DROP TRIGGER IF EXISTS trg_refresh_runs_updated_at ON public.refresh_runs")
    op.execute(
        """
        CREATE TRIGGER trg_refresh_runs_updated_at
            BEFORE UPDATE ON public.refresh_runs
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
        """.strip()
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.ensure_market_quote_placeholder()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            v_user_count INT;
        BEGIN
            NEW.user_ticker := TRIM(NEW.user_ticker);
            IF NEW.provider_symbol IS NOT NULL THEN
                NEW.provider_symbol := UPPER(TRIM(NEW.provider_symbol));

                IF NEW.provider_symbol !~ '^[A-Z0-9._\\-^=/&]{1,50}$' THEN
                    RAISE EXCEPTION 'Invalid provider_symbol format: %', NEW.provider_symbol;
                END IF;
            END IF;

            IF TG_OP = 'INSERT' THEN
                SELECT COUNT(*) INTO v_user_count
                FROM public.user_instruments
                WHERE user_id = NEW.user_id;

                IF v_user_count >= 500 THEN
                    RAISE EXCEPTION 'Watchlist limit of 500 instruments exceeded';
                END IF;
            END IF;

            IF NEW.provider_symbol IS NOT NULL THEN
                INSERT INTO public.market_quotes (provider_symbol, exchange, currency, company_name, status)
                VALUES (
                    NEW.provider_symbol,
                    COALESCE(NULLIF(TRIM(NEW.exchange), ''), 'UNKNOWN'),
                    COALESCE(NULLIF(TRIM(NEW.currency), ''), 'EUR'),
                    NULLIF(TRIM(NEW.company_name), ''),
                    'UNAVAILABLE'
                )
                ON CONFLICT (provider_symbol) DO NOTHING;
            END IF;

            RETURN NEW;
        END;
        $$
        """.strip()
    )
    op.execute("REVOKE ALL ON FUNCTION public.ensure_market_quote_placeholder() FROM PUBLIC, anon, authenticated")

    op.execute("DROP TRIGGER IF EXISTS trg_ensure_market_quote ON public.user_instruments")
    op.execute(
        """
        CREATE TRIGGER trg_ensure_market_quote
            BEFORE INSERT OR UPDATE OF provider_symbol ON public.user_instruments
            FOR EACH ROW EXECUTE FUNCTION public.ensure_market_quote_placeholder()
        """.strip()
    )

    # 8. Recreate user_positions_view with security_invoker = true and explicit grants
    op.execute(
        """
        CREATE OR REPLACE VIEW public.user_positions_view
        WITH (security_invoker = true) AS
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
            (mq.price IS NOT NULL AND mq.price > 0 AND ui.target_price IS NOT NULL AND ui.target_price > 0) AS decline_to_target_valid
        FROM public.user_instruments ui
        LEFT JOIN public.market_quotes mq ON ui.provider_symbol = mq.provider_symbol
        """.strip()
    )
    op.execute("REVOKE ALL ON public.user_positions_view FROM PUBLIC, anon")
    op.execute("GRANT SELECT ON public.user_positions_view TO authenticated, service_role")

    # 9. Enable RLS, harden privileges, drop legacy permissive policies, and create canonical policies
    op.execute("ALTER TABLE public.user_instruments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.market_quotes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.refresh_runs ENABLE ROW LEVEL SECURITY")

    op.execute("REVOKE ALL ON public.user_instruments FROM PUBLIC, anon")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_instruments TO authenticated")
    op.execute("GRANT ALL ON public.user_instruments TO service_role")

    op.execute("REVOKE ALL ON public.market_quotes FROM PUBLIC, anon")
    op.execute("REVOKE INSERT, UPDATE, DELETE ON public.market_quotes FROM authenticated")
    op.execute("GRANT SELECT ON public.market_quotes TO authenticated")
    op.execute("GRANT ALL ON public.market_quotes TO service_role")

    op.execute("REVOKE ALL ON public.refresh_runs FROM PUBLIC, anon")
    op.execute("REVOKE INSERT, UPDATE, DELETE ON public.refresh_runs FROM authenticated")
    op.execute("GRANT SELECT ON public.refresh_runs TO authenticated")
    op.execute("GRANT ALL ON public.refresh_runs TO service_role")

    # Drop legacy and canonical policies on user_instruments
    for p_name in (
        "Users view only their instruments",
        "Users insert only their instruments",
        "Users update only their instruments",
        "Users delete only their instruments",
    ):
        op.execute(f'DROP POLICY IF EXISTS "{p_name}" ON public.user_instruments')

    op.execute(
        """
        CREATE POLICY "Users view only their instruments"
            ON public.user_instruments FOR SELECT
            TO authenticated
            USING ((select auth.uid()) = user_id)
        """.strip()
    )
    op.execute(
        """
        CREATE POLICY "Users insert only their instruments"
            ON public.user_instruments FOR INSERT
            TO authenticated
            WITH CHECK ((select auth.uid()) = user_id)
        """.strip()
    )
    op.execute(
        """
        CREATE POLICY "Users update only their instruments"
            ON public.user_instruments FOR UPDATE
            TO authenticated
            USING ((select auth.uid()) = user_id)
            WITH CHECK ((select auth.uid()) = user_id)
        """.strip()
    )
    op.execute(
        """
        CREATE POLICY "Users delete only their instruments"
            ON public.user_instruments FOR DELETE
            TO authenticated
            USING ((select auth.uid()) = user_id)
        """.strip()
    )

    # market_quotes policies
    op.execute('DROP POLICY IF EXISTS "Authenticated users read global market quotes" ON public.market_quotes')
    op.execute(
        """
        CREATE POLICY "Authenticated users read global market quotes"
            ON public.market_quotes FOR SELECT
            TO authenticated
            USING (true)
        """.strip()
    )

    # refresh_runs policies (explicitly remove insecure SQL_supabase.txt policies allowing user_id IS NULL writes/reads)
    for p_name in (
        "Authenticated users read relevant refresh runs",
        "Authenticated users insert refresh runs",
        "Authenticated users update refresh runs",
        "Users view only their own refresh runs",
    ):
        op.execute(f'DROP POLICY IF EXISTS "{p_name}" ON public.refresh_runs')

    op.execute(
        """
        CREATE POLICY "Users view only their own refresh runs"
            ON public.refresh_runs FOR SELECT
            TO authenticated
            USING ((select auth.uid()) = user_id)
        """.strip()
    )


def downgrade() -> None:
    """Revert U2 alignment cleanly back to revision 2a8b9c0d1e2f."""
    bind = op.get_bind()

    if bind.dialect.name != "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_user_instruments_user_upper_ticker")
        op.execute("CREATE INDEX IF NOT EXISTS ix_refresh_runs_status ON refresh_runs (status)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_refresh_runs_user_id ON refresh_runs (user_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_user_instruments_user_id ON user_instruments (user_id)")
        return

    # 1. Drop RLS policies created in upgrade
    for p_name in (
        "Users view only their instruments",
        "Users insert only their instruments",
        "Users update only their instruments",
        "Users delete only their instruments",
    ):
        op.execute(f'DROP POLICY IF EXISTS "{p_name}" ON public.user_instruments')
    op.execute('DROP POLICY IF EXISTS "Authenticated users read global market quotes" ON public.market_quotes')
    op.execute('DROP POLICY IF EXISTS "Users view only their own refresh runs" ON public.refresh_runs')

    # 2. Drop view and triggers/functions before column type reversion
    op.execute("DROP VIEW IF EXISTS public.user_positions_view")
    op.execute("DROP TRIGGER IF EXISTS trg_ensure_market_quote ON public.user_instruments")
    op.execute("DROP TRIGGER IF EXISTS trg_user_instruments_updated_at ON public.user_instruments")
    op.execute("DROP TRIGGER IF EXISTS trg_refresh_runs_updated_at ON public.refresh_runs")
    op.execute("DROP FUNCTION IF EXISTS public.ensure_market_quote_placeholder()")
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at()")

    # 3. Drop CHECK constraints added in upgrade
    for tbl, cname in (
        ("market_quotes", "chk_market_quotes_price_pos"),
        ("market_quotes", "chk_market_quotes_prev_close_pos"),
        ("market_quotes", "chk_market_quotes_status"),
        ("market_quotes", "chk_market_quotes_symbol_format"),
        ("user_instruments", "chk_user_instruments_analysis_price_pos"),
        ("user_instruments", "chk_user_instruments_soy_price_pos"),
        ("user_instruments", "chk_user_instruments_target_price_pos"),
        ("user_instruments", "chk_user_ticker_length"),
        ("user_instruments", "chk_provider_symbol_format"),
        ("refresh_runs", "chk_refresh_runs_status"),
        ("refresh_runs", "chk_counts_nonneg"),
        ("refresh_runs", "chk_completed_after_start"),
    ):
        op.execute(f"ALTER TABLE public.{tbl} DROP CONSTRAINT IF EXISTS {cname}")

    # 4. Drop functional index and revert NUMERIC(20, 6) -> NUMERIC(18, 6)
    op.execute("DROP INDEX IF EXISTS public.idx_user_instruments_user_upper_ticker")
    op.execute(
        """
        ALTER TABLE public.market_quotes
            ALTER COLUMN price TYPE NUMERIC(18, 6),
            ALTER COLUMN previous_close TYPE NUMERIC(18, 6)
        """.strip()
    )
    op.execute(
        """
        ALTER TABLE public.user_instruments
            ALTER COLUMN analysis_reference_price TYPE NUMERIC(18, 6),
            ALTER COLUMN start_of_year_price TYPE NUMERIC(18, 6),
            ALTER COLUMN target_price TYPE NUMERIC(18, 6)
        """.strip()
    )

    # 5. Restore legacy single-column indexes
    op.execute("CREATE INDEX IF NOT EXISTS ix_refresh_runs_status ON public.refresh_runs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_refresh_runs_user_id ON public.refresh_runs (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_instruments_user_id ON public.user_instruments (user_id)")
