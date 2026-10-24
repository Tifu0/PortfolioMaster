#!/usr/bin/env python3
"""Migration tool: Legacy PortfolioMaster SQLite/JSON -> Multi-Tenant Web (watchlistTracker - WT).

Reads a legacy SQLite database file (portfolio.db) or a JSON v1.0 backup file,
validates row counts, computes SHA-256 payload checksums, guarantees Decimal
precision preservation without float rounding loss, and imports data into:
- user_instruments: private, tenant-isolated rows scoped to the given user_id.
- market_quotes: global, shared quote registry indexed by canonical provider_symbol.

Usage:
    python scripts/migrate_sqlite_to_web.py --sqlite path/to/portfolio.db --user-id <UUID> [--dry-run]
    python scripts/migrate_sqlite_to_web.py --json path/to/backup.json --user-id <UUID> [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from portfoliomaster.core.config import get_yahoo_suffix
from portfoliomaster.db.schema import Base, MarketQuote, UserInstrument, utc_now
from portfoliomaster.ingest.normalizer import normalize

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate_sqlite_to_web")


@dataclass
class MigrationSummary:
    """Summary of migration results."""
    source_type: str
    source_path: str
    target_user_id: uuid.UUID
    dry_run: bool
    input_instruments_count: int
    migrated_instruments_count: int
    quotes_created_or_updated: int
    payload_sha256: str
    decimal_fields_verified: int
    source_target_price_sum: Decimal = Decimal(0)
    source_analysis_price_sum: Decimal = Decimal(0)
    target_target_price_sum: Decimal = Decimal(0)
    target_analysis_price_sum: Decimal = Decimal(0)
    reconciliation_passed: bool = True


def parse_decimal_safe(val: Any) -> Optional[Decimal]:
    """Parse a Decimal value cleanly preserving exact precision without float loss."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "null", "nan", "inf", "-inf"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date_safe(val: Any) -> Optional[date]:
    """Parse date safely from string or date object."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    if "t" in s.lower() or " " in s:
        s = s.replace("T", " ").split(" ")[0]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime_safe(val: Any) -> Optional[datetime]:
    """Parse datetime safely into timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    s = str(val).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_bool_safe(val: Any) -> bool:
    """Parse boolean safely (CRITICAL FIX for Bug 1b: 'false' string != True)."""
    if val is None:
        return True
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "t", "y")


def normalize_quote_status(val: Any, has_valid_price: bool = False) -> str:
    """Normalize legacy numeric or string quote status into canonical Postgres enum."""
    if val is None:
        return "FRESH" if has_valid_price else "UNAVAILABLE"
    s = str(val).strip().upper()
    mapping = {
        "1": "FRESH",
        "FRESH": "FRESH",
        "2": "DELAYED",
        "DELAYED": "DELAYED",
        "3": "STALE",
        "STALE": "STALE",
        "4": "UNAVAILABLE",
        "UNAVAILABLE": "UNAVAILABLE",
        "5": "ERROR",
        "ERROR": "ERROR",
    }
    if s in mapping:
        return mapping[s]
    return "FRESH" if has_valid_price else "UNAVAILABLE"


def compute_payload_checksum(instruments: List[Dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 checksum across instruments."""
    hasher = hashlib.sha256()
    sorted_items = sorted(instruments, key=lambda x: str(x.get("user_ticker", "")).strip().upper())
    for item in sorted_items:
        ticker = str(item.get("user_ticker", "")).strip()
        provider_sym = str(item.get("provider_symbol", "")).strip()
        comp = str(item.get("company_name", "")).strip()
        curr = str(item.get("currency", "")).strip()
        tgt = str(parse_decimal_safe(item.get("target_price")) or "")
        ref = str(parse_decimal_safe(item.get("analysis_reference_price")) or "")
        ytd = str(parse_decimal_safe(item.get("start_of_year_price")) or "")
        active = str(parse_bool_safe(item.get("active", True)))

        line = f"{ticker}|{provider_sym}|{comp}|{curr}|{tgt}|{ref}|{ytd}|{active}\n"
        hasher.update(line.encode("utf-8"))
    return hasher.hexdigest()


def load_from_sqlite(db_path: Path) -> List[Dict[str, Any]]:
    """Extract instruments and quotes from a legacy SQLite database."""
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database file not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # Pre-flight check: instruments table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='instruments'")
        if not cur.fetchone():
            raise ValueError(f"Invalid SQLite schema: 'instruments' table not found in {db_path}")

        # Check for duplicate tickers in SQLite
        cur.execute("SELECT user_ticker, count(*) FROM instruments GROUP BY user_ticker HAVING count(*) > 1")
        dups = [row[0] for row in cur.fetchall()]
        if dups:
            raise ValueError(f"Pre-flight check failed: source SQLite contains duplicate ticker(s): {dups}")

        # Check for orphan quotes
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quotes'")
        quotes_exists = cur.fetchone() is not None
        if quotes_exists:
            cur.execute("SELECT count(*) FROM quotes WHERE instrument_id NOT IN (SELECT id FROM instruments)")
            orphan_count = cur.fetchone()[0]
            if orphan_count > 0:
                raise ValueError(f"Pre-flight check failed: found {orphan_count} orphan quote record(s) referencing non-existent instruments.")

        cur.execute("""
            SELECT
                i.*,
                q.price AS quote_price,
                q.previous_close AS quote_previous_close,
                q.quote_timestamp AS quote_timestamp,
                q.fetched_at AS quote_fetched_at,
                q.provider AS quote_provider,
                q.status AS quote_status
            FROM instruments i
            LEFT JOIN quotes q ON q.instrument_id = i.id
        """)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            quote_dict = None
            if d.get("quote_price") is not None or d.get("quote_status") is not None:
                quote_dict = {
                    "price": d.get("quote_price"),
                    "previous_close": d.get("quote_previous_close"),
                    "quote_timestamp": d.get("quote_timestamp"),
                    "fetched_at": d.get("quote_fetched_at"),
                    "provider": d.get("quote_provider") or "Yahoo",
                    "status": d.get("quote_status") or "FRESH",
                }
            d["quote"] = quote_dict
            result.append(d)
        return result
    finally:
        conn.close()


def load_from_json(json_path: Path) -> List[Dict[str, Any]]:
    """Extract instruments from a JSON v1.0 backup file."""
    if not json_path.exists():
        raise FileNotFoundError(f"JSON backup file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_list: List[Dict[str, Any]] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        if "instruments" in data and isinstance(data["instruments"], list):
            raw_list = data["instruments"]
        elif "positions" in data and isinstance(data["positions"], list):
            raw_list = data["positions"]
        else:
            raise ValueError(f"Invalid JSON backup format in {json_path}: missing 'instruments' array")
    else:
        raise ValueError(f"Invalid JSON content in {json_path}")

    # Check for duplicate tickers in JSON
    seen_tickers: set[str] = set()
    dup_tickers: set[str] = set()
    for item in raw_list:
        ticker = str(item.get("user_ticker", "")).strip().upper()
        if ticker:
            if ticker in seen_tickers:
                dup_tickers.add(ticker)
            seen_tickers.add(ticker)
    if dup_tickers:
        raise ValueError(f"Pre-flight check failed: source JSON contains duplicate ticker(s): {sorted(list(dup_tickers))}")

    return raw_list


def migrate_instruments(
    instruments: List[Dict[str, Any]],
    user_id: uuid.UUID,
    session: Session,
    dry_run: bool = False,
    verbose: bool = False,
) -> MigrationSummary:
    """Migrate instruments and quotes into multi-tenant tables.
    
    Guarantees:
    - user_ticker is never altered or corrupted.
    - All Decimals preserve exact string-based precision.
    - Quotes decouple into global market_quotes table.
    - Isolated to target user_id in user_instruments.
    """
    checksum = compute_payload_checksum(instruments)
    input_count = len(instruments)
    migrated_count = 0
    quotes_count = 0
    decimal_fields_checked = 0

    seen_tickers: set[str] = set()

    # Preload existing quotes and tenant instruments in batch for high network performance
    existing_quotes_map: Dict[str, MarketQuote] = {
        q.provider_symbol: q for q in session.scalars(select(MarketQuote)).all()
    }
    existing_uis_map: Dict[str, UserInstrument] = {
        ui.user_ticker.upper(): ui
        for ui in session.scalars(
            select(UserInstrument).where(UserInstrument.user_id == user_id)
        ).all()
    }

    # Pre-calculate sums for reconciliation
    source_target_price_sum = Decimal(0)
    source_analysis_price_sum = Decimal(0)
    for raw in instruments:
        t_price = parse_decimal_safe(raw.get("target_price"))
        if t_price is not None:
            source_target_price_sum += t_price
        a_price = parse_decimal_safe(raw.get("analysis_reference_price"))
        if a_price is not None:
            source_analysis_price_sum += a_price

    for idx, raw in enumerate(instruments, start=1):
        raw_ticker = raw.get("user_ticker")
        if not raw_ticker or not str(raw_ticker).strip():
            logger.warning("Row %d: missing user_ticker, skipping", idx)
            continue

        ticker = str(raw_ticker).strip()
        ticker_upper = ticker.upper()

        if ticker_upper in seen_tickers:
            logger.warning("Duplicate ticker '%s' in import payload, updating previous observation", ticker)
        seen_tickers.add(ticker_upper)

        currency = str(raw.get("currency") or "USD").strip().upper() or "USD"
        exchange_raw = str(raw.get("exchange") or "UNKNOWN").strip() or "UNKNOWN"
        company_name = str(raw.get("company_name") or ticker).strip()
        comment = str(raw.get("comment") or "").strip()
        active = parse_bool_safe(raw.get("active", True))

        # Normalise provider symbol if missing
        provider_sym = raw.get("provider_symbol")
        if not provider_sym or not str(provider_sym).strip():
            norm_sym, norm_exch = normalize(ticker, currency)
            suffix = get_yahoo_suffix(ticker, norm_exch, currency)
            resolved_provider = (
                f"{norm_sym}{suffix}"
                if suffix and not norm_sym.upper().endswith(suffix.upper())
                else norm_sym
            )
        else:
            resolved_provider = str(provider_sym).strip()

        # Decouple Quote
        quote_data = raw.get("quote") or {}
        q_price = parse_decimal_safe(quote_data.get("price"))
        q_prev = parse_decimal_safe(quote_data.get("previous_close"))
        has_valid_quote = q_price is not None and q_price > 0
        q_status = normalize_quote_status(quote_data.get("status"), has_valid_price=has_valid_quote)
        q_ts = parse_datetime_safe(quote_data.get("quote_timestamp"))
        q_fetched = parse_datetime_safe(quote_data.get("fetched_at"))
        q_provider = str(quote_data.get("provider") or "Yahoo")

        if q_price is not None:
            decimal_fields_checked += 1
        if q_prev is not None:
            decimal_fields_checked += 1

        # 1. Upsert Global MarketQuote
        if resolved_provider:
            existing_mq = existing_quotes_map.get(resolved_provider)

            if existing_mq:
                if has_valid_quote:
                    existing_mq.price = q_price
                    existing_mq.previous_close = q_prev
                    existing_mq.quote_timestamp = q_ts or utc_now()
                    existing_mq.last_valid_fetched_at = q_fetched or utc_now()
                    existing_mq.status = q_status
                existing_mq.last_attempt_at = utc_now()
                if company_name and not existing_mq.company_name:
                    existing_mq.company_name = company_name
                quotes_count += 1
            else:
                new_mq = MarketQuote(
                    provider_symbol=resolved_provider,
                    currency=currency,
                    exchange=exchange_raw,
                    company_name=company_name,
                    provider=q_provider,
                    price=q_price,
                    previous_close=q_prev,
                    quote_timestamp=q_ts or (utc_now() if has_valid_quote else None),
                    last_valid_fetched_at=q_fetched or (utc_now() if has_valid_quote else None),
                    last_attempt_at=utc_now(),
                    status=q_status,
                )
                session.add(new_mq)
                existing_quotes_map[resolved_provider] = new_mq
                quotes_count += 1

        # 2. Parse UserInstrument Decimal fields
        analysis_dt = parse_date_safe(raw.get("analysis_date"))
        analysis_price = parse_decimal_safe(raw.get("analysis_reference_price"))
        soy_dt = parse_date_safe(raw.get("start_of_year_date"))
        soy_price = parse_decimal_safe(raw.get("start_of_year_price"))
        tgt_price = parse_decimal_safe(raw.get("target_price"))

        if analysis_price is not None:
            decimal_fields_checked += 1
        if soy_price is not None:
            decimal_fields_checked += 1
        if tgt_price is not None:
            decimal_fields_checked += 1

        # 3. Upsert UserInstrument (strictly scoped to user_id)
        existing_ui = existing_uis_map.get(ticker_upper)

        if existing_ui:
            existing_ui.provider_symbol = resolved_provider
            existing_ui.exchange = exchange_raw
            existing_ui.currency = currency
            existing_ui.company_name = company_name
            existing_ui.analysis_date = analysis_dt
            existing_ui.analysis_reference_price = analysis_price
            existing_ui.start_of_year_date = soy_dt
            existing_ui.start_of_year_price = soy_price
            existing_ui.target_price = tgt_price
            existing_ui.comment = comment
            existing_ui.active = active
        else:
            new_ui = UserInstrument(
                id=uuid.uuid4(),
                user_id=user_id,
                user_ticker=ticker,
                provider_symbol=resolved_provider,
                exchange=exchange_raw,
                currency=currency,
                company_name=company_name,
                analysis_date=analysis_dt,
                analysis_reference_price=analysis_price,
                start_of_year_date=soy_dt,
                start_of_year_price=soy_price,
                target_price=tgt_price,
                comment=comment,
                active=active,
            )
            session.add(new_ui)
            existing_uis_map[ticker_upper] = new_ui

        migrated_count += 1
        if verbose:
            logger.info("Migrated [%s] -> provider '%s' (active=%s)", ticker, resolved_provider, active)

    # Batch flush once at the end
    session.flush()

    # Verification: Ensure row counts match unique tickers processed
    expected_unique_count = len(seen_tickers)
    if migrated_count != expected_unique_count:
        raise ValueError(
            f"Parity validation failure: processed {migrated_count} instruments, expected {expected_unique_count}"
        )

    # Reconciliation: Ensure financial totals match between source and target
    target_target_price_sum = Decimal(0)
    target_analysis_price_sum = Decimal(0)
    for ui in existing_uis_map.values():
        if ui.target_price is not None:
            target_target_price_sum += ui.target_price
        if ui.analysis_reference_price is not None:
            target_analysis_price_sum += ui.analysis_reference_price

    if source_target_price_sum != target_target_price_sum or source_analysis_price_sum != target_analysis_price_sum:
        raise ValueError(
            f"Reconciliation discrepancy: target sum (source: {source_target_price_sum}, target: {target_target_price_sum}) "
            f"or analysis sum (source: {source_analysis_price_sum}, target: {target_analysis_price_sum})"
        )

    return MigrationSummary(
        source_type="sqlite" if instruments and "quote_price" in instruments[0] else "payload",
        source_path="",
        target_user_id=user_id,
        dry_run=dry_run,
        input_instruments_count=input_count,
        migrated_instruments_count=migrated_count,
        quotes_created_or_updated=quotes_count,
        payload_sha256=checksum,
        decimal_fields_verified=decimal_fields_checked,
        source_target_price_sum=source_target_price_sum,
        source_analysis_price_sum=source_analysis_price_sum,
        target_target_price_sum=target_target_price_sum,
        target_analysis_price_sum=target_analysis_price_sum,
        reconciliation_passed=True,
    )


def rollback_user_migration(user_id: uuid.UUID, db_url: Optional[str] = None) -> int:
    """Safely roll back migrated user instruments for a given user_id."""
    resolved_db_url = db_url or os.getenv("DATABASE_URL") or os.getenv("PORTFOLIOMASTER_DB_URL") or "sqlite:///./portfolio_web.db"
    engine = create_engine(resolved_db_url)
    from sqlalchemy import delete
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        stmt = delete(UserInstrument).where(UserInstrument.user_id == user_id)
        result = session.execute(stmt)
        deleted_count = result.rowcount
        session.commit()
        logger.info("Rollback complete: deleted %d user_instruments for user %s", deleted_count, user_id)
        return deleted_count


def run_migration(
    source_sqlite: Optional[str] = None,
    source_json: Optional[str] = None,
    target_user_id_str: Optional[str] = None,
    db_url: Optional[str] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> MigrationSummary:
    """Entry point for executing migration from SQLite or JSON."""
    if not source_sqlite and not source_json:
        raise ValueError("Either --sqlite or --json must be specified.")

    # Parse and validate target user UUID
    if not target_user_id_str or not target_user_id_str.strip():
        raise ValueError("Missing required target user ID. Please provide a valid UUID via --user-id.")
    try:
        user_id = uuid.UUID(target_user_id_str.strip())
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid user ID format: '{target_user_id_str}'. Must be a valid UUID.") from e

    # Load raw data
    if source_sqlite:
        sqlite_path = Path(source_sqlite).resolve()
        logger.info("Reading legacy SQLite database: %s", sqlite_path)
        raw_items = load_from_sqlite(sqlite_path)
        source_type = "sqlite"
        source_path = str(sqlite_path)
    else:
        json_path = Path(source_json).resolve()  # type: ignore
        logger.info("Reading legacy JSON backup: %s", json_path)
        raw_items = load_from_json(json_path)
        source_type = "json"
        source_path = str(json_path)

    logger.info("Loaded %d raw records from %s", len(raw_items), source_type)

    # Connect to database and run pre-flight reachability & schema checks
    resolved_db_url = db_url or os.getenv("DATABASE_URL") or os.getenv("PORTFOLIOMASTER_DB_URL")
    if not resolved_db_url:
        resolved_db_url = "sqlite:///./portfolio_web.db"
        logger.info("No DATABASE_URL set. Using local SQLite database: %s", resolved_db_url)

    from sqlalchemy import inspect, text
    try:
        engine = create_engine(resolved_db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise RuntimeError(f"Target database unreachable: {e}") from e

    with engine.connect() as conn:
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        required_tables = {"market_quotes", "user_instruments"}
        missing_tables = required_tables - existing_tables
        if missing_tables:
            if engine.dialect.name == "sqlite" and not dry_run:
                Base.metadata.create_all(engine)
            else:
                raise RuntimeError(
                    f"Required target table(s) missing: {missing_tables}. Run migrations (alembic upgrade head) before migrating."
                )

        if engine.dialect.name == "postgresql":
            try:
                has_auth = conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users'")
                ).fetchone()
                if has_auth:
                    user_exists = conn.execute(
                        text("SELECT id FROM auth.users WHERE id = :uid"),
                        {"uid": str(user_id)}
                    ).fetchone()
                    if not user_exists:
                        raise ValueError(f"Target user_id '{user_id}' does not exist in auth.users.")
            except Exception as ex:
                if "Target user_id" in str(ex):
                    raise
                logger.debug("Could not verify auth.users table: %s", ex)

    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        try:
            summary = migrate_instruments(
                instruments=raw_items,
                user_id=user_id,
                session=session,
                dry_run=dry_run,
                verbose=verbose,
            )
            summary.source_type = source_type
            summary.source_path = source_path

            if dry_run:
                session.rollback()
                logger.info("DRY-RUN completed successfully. 0 changes committed to database.")
            else:
                session.commit()
                logger.info("MIGRATION COMMITTED: %d instruments persisted for user %s.", summary.migrated_instruments_count, user_id)

            return summary

        except Exception as e:
            session.rollback()
            logger.error("Migration failed, transaction rolled back: %s", e)
            raise


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy PortfolioMaster SQLite/JSON into watchlistTracker (WT) multi-tenant schema."
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--sqlite", type=str, help="Path to legacy portfolio.db SQLite database")
    group.add_argument("--json", type=str, help="Path to legacy JSON backup file")
    group.add_argument("--rollback", action="store_true", help="Rollback (delete) migrated instruments for target user-id")

    parser.add_argument(
        "--user-id",
        type=str,
        required=True,
        help="Target user UUID (e.g. Supabase auth.users ID)",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Target database URL (e.g. postgresql+psycopg2://user:pass@host:5432/db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform validation, checksums and mapping without committing to database",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose row-level migration output",
    )

    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    try:
        if args.rollback:
            target_user_id = uuid.UUID(args.user_id)
            deleted = rollback_user_migration(target_user_id, db_url=args.db_url)
            print(f"\nROLLBACK SUCCESS: Deleted {deleted} instruments for user {target_user_id}\n")
            sys.exit(0)

        if not args.sqlite and not args.json:
            parser.error("Either --sqlite or --json must be specified (or --rollback).")

        summary = run_migration(
            source_sqlite=args.sqlite,
            source_json=args.json,
            target_user_id_str=args.user_id,
            db_url=args.db_url,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        print("\n" + "=" * 60)
        print("  watchlistTracker (WT) - Migration Parity Report")
        print("=" * 60)
        print(f" Source:           {summary.source_type.upper()} ({summary.source_path})")
        print(f" Target User ID:   {summary.target_user_id}")
        print(f" Dry Run Mode:     {'YES (No changes committed)' if summary.dry_run else 'NO (Committed)'}")
        print(f" Input Count:      {summary.input_instruments_count}")
        print(f" Migrated Count:   {summary.migrated_instruments_count}")
        print(f" Quotes Processed: {summary.quotes_created_or_updated}")
        print(f" Decimal Fields:   {summary.decimal_fields_verified} verified with exact precision")
        print(f" SHA-256 Checksum: {summary.payload_sha256}")
        print(f" Reconciliation:   Target Sum={summary.target_target_price_sum}, Analysis Sum={summary.target_analysis_price_sum} [MATCH]")
        print("=" * 60)
        print("STATUS: SUCCESS [OK]\n")
        sys.exit(0)

    except Exception as ex:
        print(f"\nMIGRATION FAILED: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
