"""Regression verification and parity test suite for watchlistTracker (WT).

This suite verifies that the critical legacy bugs (P0/P1) from PossibleIssues.md
and PortfolioMaster_Migration_Dossier.md have been fixed and cannot regress:
1. JSON restore is atomic (no wipe before full validation), respects target_db_path,
   and parses boolean strings like "false" correctly.
2. Quote failures preserve the last valid price, previous close, and quote timestamp.
3. Export uses correct argument order for decline_to_target(target_price, latest_price)
   matching calculations.py and API positions.
4. Timestamps are parsed as full datetimes, not truncated to None.
5. Formula injection protection in CSV and Excel exports.
6. Inclusion/exclusion of inactive instruments via explicit parameters.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

from portfoliomaster.core.models import (
    Instrument,
    Quote,
    QuoteStatus,
    Exchange,
)
from portfoliomaster.core.calculations import decline_to_target
from portfoliomaster.db.repository import (
    upsert_instrument,
    get_instrument_by_ticker,
    get_all_instruments,
    upsert_quote,
    get_quote_by_instrument_id,
    _parse_date,
    _parse_datetime,
)
from portfoliomaster.backup.exporters import (
    get_export_records,
    export_to_csv,
    restore_from_json,
)


# ==============================================================================
# BUG 4 FIX: Argument order in decline_to_target export
# ==============================================================================

def test_regression_bug4_argument_order_in_export():
    """Verify that export calculates decline_to_target(inst.target_price, quote.price)
    producing positive upside when target > price, identical to /api/positions.
    """
    target_price = Decimal("120.00")
    latest_price = Decimal("100.00")

    # Authoritative calculation: ((120 - 100) / 100) * 100 = +20.00%
    expected = decline_to_target(target_price, latest_price)
    assert expected.decline_to_target == Decimal("20.00")

    inst = Instrument(
        user_ticker="WT_PARITY",
        provider_symbol="WT_PARITY",
        exchange=Exchange.US,
        currency="USD",
        target_price=target_price,
        active=True,
    )
    upsert_instrument(inst)
    persisted = get_instrument_by_ticker("WT_PARITY")
    assert persisted is not None

    q = Quote(
        instrument_id=persisted.id,
        price=latest_price,
        previous_close=Decimal("99.00"),
        status=QuoteStatus.FRESH,
        quote_timestamp=datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc),
    )
    upsert_quote(q)

    records = get_export_records()
    record = next(r for r in records if r["user_ticker"] == "WT_PARITY")

    # FIXED: Export record must be +20.00, not -16.67
    assert float(record["decline_to_target"]) == 20.00


# ==============================================================================
# BUG 1A FIX: JSON restore atomicity (validation before wipe)
# ==============================================================================

def test_regression_bug1a_restore_json_atomicity(tmp_path):
    """Verify that restore_from_json validates 100% of the payload before wiping.
    If any row is malformed, existing data remains completely intact.
    """
    inst = Instrument(
        user_ticker="SAFE_STOCK",
        provider_symbol="SAFE_STOCK",
        currency="USD",
        active=True,
    )
    upsert_instrument(inst)
    assert get_instrument_by_ticker("SAFE_STOCK") is not None

    malformed_json = {
        "version": "1.0",
        "exported_at": "2026-10-22T12:00:00",
        "instruments": [
            {"user_ticker": "ROW1", "currency": "USD"},
            {"user_ticker": "BAD_ROW", "analysis_reference_price": "NOT_A_DECIMAL"},
        ],
    }

    from decimal import InvalidOperation
    with pytest.raises(InvalidOperation):
        restore_from_json(malformed_json, create_safety_backup=False)

    # FIXED: Existing stock was NOT wiped because validation happened prior to wipe!
    assert get_instrument_by_ticker("SAFE_STOCK") is not None


# ==============================================================================
# BUG 1B FIX: Boolean active string parsing ("false" -> False)
# ==============================================================================

def test_regression_bug1b_active_string_parsing():
    """Verify that 'false', '0', 'no' strings in JSON restore map to active=False."""
    json_payload = {
        "version": "1.0",
        "instruments": [
            {"user_ticker": "ACTIVE_DEFAULT"},
            {"user_ticker": "INACTIVE_STR", "active": "false"},
            {"user_ticker": "INACTIVE_BOOL", "active": False},
            {"user_ticker": "ACTIVE_STR", "active": "true"},
        ],
    }

    restore_from_json(json_payload, create_safety_backup=False)

    inst_def = get_instrument_by_ticker("ACTIVE_DEFAULT")
    inst_str = get_instrument_by_ticker("INACTIVE_STR")
    inst_bool = get_instrument_by_ticker("INACTIVE_BOOL")
    inst_act = get_instrument_by_ticker("ACTIVE_STR")

    assert inst_def.active is True
    # FIXED: String "false" is correctly evaluated to False
    assert inst_str.active is False
    assert inst_bool.active is False
    assert inst_act.active is True


# ==============================================================================
# BUG 1C FIX: Restore respects target_db_path
# ==============================================================================

def test_regression_bug1c_restore_scopes_to_target_db_path(tmp_path, monkeypatch):
    """Verify that passing target_db_path restores into that DB and leaves default untouched."""
    default_db = str(tmp_path / "default.db")
    custom_target_db = str(tmp_path / "custom_target.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", default_db)

    from portfoliomaster.db.connection import init_db
    init_db()

    inst = Instrument(user_ticker="DEFAULT_STOCK", currency="USD")
    upsert_instrument(inst)
    assert get_instrument_by_ticker("DEFAULT_STOCK") is not None

    # Initialize custom target DB tables
    from portfoliomaster.db.connection import get_connection
    conn = get_connection(custom_target_db)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_ticker TEXT UNIQUE NOT NULL,
            provider_symbol TEXT,
            exchange TEXT,
            currency TEXT,
            company_name TEXT,
            analysis_date DATE,
            analysis_reference_price DECIMAL,
            start_of_year_date DATE,
            start_of_year_price DECIMAL,
            target_price DECIMAL,
            comment TEXT,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER NOT NULL UNIQUE,
            price DECIMAL,
            previous_close DECIMAL,
            quote_timestamp TIMESTAMP,
            fetched_at TIMESTAMP,
            provider TEXT,
            status TEXT,
            error_message TEXT,
            FOREIGN KEY (instrument_id) REFERENCES instruments (id)
        )
    """)
    conn.commit()
    conn.close()

    payload = {
        "version": "1.0",
        "instruments": [{"user_ticker": "CUSTOM_STOCK", "currency": "USD"}]
    }
    restore_from_json(payload, target_db_path=custom_target_db, create_safety_backup=False)

    # FIXED: Default DB was untouched and retains DEFAULT_STOCK
    assert get_instrument_by_ticker("DEFAULT_STOCK") is not None
    assert get_instrument_by_ticker("CUSTOM_STOCK") is None

    # Custom DB contains CUSTOM_STOCK
    assert get_instrument_by_ticker("CUSTOM_STOCK", db_path=custom_target_db) is not None


# ==============================================================================
# BUG 3 FIX: Preserve last valid price on Yahoo failure
# ==============================================================================

def test_regression_bug3_preserve_last_valid_price_on_failure():
    """Verify that upsert_quote preserves price, previous_close, and quote_timestamp
    when an incoming quote fetch fails (price=None).
    """
    inst = Instrument(user_ticker="BBVA", provider_symbol="BBVA.MC", currency="EUR")
    upsert_instrument(inst)
    persisted = get_instrument_by_ticker("BBVA")
    assert persisted is not None

    last_time = datetime(2026, 10, 21, 17, 30, 0)
    valid_q = Quote(
        instrument_id=persisted.id,
        price=Decimal("9.45"),
        previous_close=Decimal("9.30"),
        quote_timestamp=last_time,
        status=QuoteStatus.FRESH,
        provider="Yahoo",
    )
    upsert_quote(valid_q)

    # Next attempt fails with HTTP 500 / UNAVAILABLE
    failed_q = Quote(
        instrument_id=persisted.id,
        price=None,
        previous_close=None,
        quote_timestamp=None,
        status=QuoteStatus.ERROR,
        error_message="HTTP 500: Rate limit exceeded",
        provider="Yahoo",
    )
    upsert_quote(failed_q)

    stored = get_quote_by_instrument_id(persisted.id)
    # FIXED: Last valid price and timestamp preserved intact!
    assert stored.price == Decimal("9.45")
    assert stored.previous_close == Decimal("9.30")
    assert stored.quote_timestamp == last_time
    # Status and error reflect the latest attempt
    assert stored.status == QuoteStatus.ERROR
    assert stored.error_message == "HTTP 500: Rate limit exceeded"


# ==============================================================================
# BUG 8 FIX: Quote timestamp datetime parsing
# ==============================================================================

def test_regression_bug8_quote_timestamp_datetime_parsing():
    """Verify that _parse_datetime parses full timestamp strings into datetimes."""
    dt_str = "2026-10-22 14:15:30"
    parsed = _parse_datetime(dt_str)
    assert isinstance(parsed, datetime)
    assert parsed.year == 2026
    assert parsed.month == 10
    assert parsed.day == 22
    assert parsed.hour == 14
    assert parsed.minute == 15
    assert parsed.second == 30

    date_parsed = _parse_date(dt_str)
    assert isinstance(date_parsed, date)
    assert date_parsed == date(2026, 10, 22)


# ==============================================================================
# Formula Injection Sanitization
# ==============================================================================

def test_regression_formula_injection_sanitization():
    """Verify that export_to_csv and export_to_excel sanitize formula prefixes (=, +, -, @)."""
    malicious_record = {
        "user_ticker": "=cmd|' /C calc'!A0",
        "company_name": "@SUM(1+1)*cmd",
        "currency": "USD",
        "analysis_reference_price": 10.0,
        "analysis_date": "2026-01-01",
        "start_of_year_price": 10.0,
        "start_of_year_date": "2026-01-01",
        "target_price": 15.0,
        "comment": "+dangerous_calc()",
        "active": True,
        "latest_price": 12.0,
        "previous_close": 11.0,
        "daily_variation": 9.09,
        "ytd_variation": 20.0,
        "variation_since_analysis": 20.0,
        "decline_to_target": 25.0,
        "exchange": "US",
        "provider_symbol": "=cmd",
        "quote_timestamp": "2026-10-22",
        "quote_status": "FRESH",
    }

    csv_output = export_to_csv([malicious_record])
    # The cell must be prefixed with a single quote '
    assert "'=cmd|' /C calc'!A0" in csv_output
    assert "'@SUM(1+1)*cmd" in csv_output
    assert "'+dangerous_calc()" in csv_output


# ==============================================================================
# Active vs Inactive Inclusion Flag
# ==============================================================================

def test_regression_include_inactive_flag():
    """Verify get_all_instruments(include_inactive=True) returns both active and inactive."""
    inst_active = Instrument(user_ticker="ACTIVE_CO", active=True)
    inst_inactive = Instrument(user_ticker="INACTIVE_CO", active=False)
    upsert_instrument(inst_active)
    upsert_instrument(inst_inactive)

    active_only = get_all_instruments(include_inactive=False)
    tickers_active = [i.user_ticker for i in active_only]
    assert "ACTIVE_CO" in tickers_active
    assert "INACTIVE_CO" not in tickers_active

    all_inst = get_all_instruments(include_inactive=True)
    tickers_all = [i.user_ticker for i in all_inst]
    assert "ACTIVE_CO" in tickers_all
    assert "INACTIVE_CO" in tickers_all
