import sqlite3
from datetime import date, datetime
from decimal import Decimal

from .connection import get_connection
from ..core.models import Quote, Instrument
from ..core.models import Exchange

def _exchange_value(exchange) -> str:
    """Return the string value of an Exchange enum or a plain string."""
    if exchange is None:
        return Exchange.UNKNOWN.value
    if isinstance(exchange, Exchange):
        return exchange.value
    # already a string (or something str-like)
    return str(exchange)


def _sql_value(value):
    """Convert values SQLite cannot bind natively (Decimal, date)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def wipe_database():
    """Wipe all data from instruments and quotes."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quotes")
    cursor.execute("DELETE FROM instruments")
    conn.commit()
    conn.close()


def upsert_instrument(instrument: Instrument):
    """Insert or update an instrument by user_ticker."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO instruments (
            user_ticker, provider_symbol, exchange, currency, company_name,
            analysis_date, analysis_reference_price, start_of_year_date, start_of_year_price,
            target_price, comment, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_ticker) DO UPDATE SET
            provider_symbol = excluded.provider_symbol,
            exchange = excluded.exchange,
            currency = excluded.currency,
            company_name = excluded.company_name,
            analysis_date = excluded.analysis_date,
            analysis_reference_price = excluded.analysis_reference_price,
            start_of_year_date = COALESCE(excluded.start_of_year_date, instruments.start_of_year_date),
            start_of_year_price = COALESCE(excluded.start_of_year_price, instruments.start_of_year_price),
            target_price = excluded.target_price,
            comment = excluded.comment,
            active = excluded.active,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            instrument.user_ticker,
            instrument.provider_symbol,
            _exchange_value(instrument.exchange),
            instrument.currency,
            instrument.company_name,
            _sql_value(instrument.analysis_date),
            _sql_value(instrument.analysis_reference_price),
            _sql_value(instrument.start_of_year_date),
            _sql_value(instrument.start_of_year_price),
            _sql_value(instrument.target_price),
            instrument.comment,
            int(instrument.active),
        ),
    )
    conn.commit()
    conn.close()


def update_instrument_by_id(instrument: Instrument):
    """Update an instrument by its database primary key id."""
    if not instrument.id:
        return upsert_instrument(instrument)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE instruments SET
            user_ticker = ?,
            provider_symbol = ?,
            exchange = ?,
            currency = ?,
            company_name = ?,
            analysis_date = ?,
            analysis_reference_price = ?,
            start_of_year_date = ?,
            start_of_year_price = ?,
            target_price = ?,
            comment = ?,
            active = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            instrument.user_ticker,
            instrument.provider_symbol,
            _exchange_value(instrument.exchange),
            instrument.currency,
            instrument.company_name,
            _sql_value(instrument.analysis_date),
            _sql_value(instrument.analysis_reference_price),
            _sql_value(instrument.start_of_year_date),
            _sql_value(instrument.start_of_year_price),
            _sql_value(instrument.target_price),
            instrument.comment,
            int(instrument.active),
            instrument.id,
        ),
    )
    conn.commit()
    conn.close()


def upsert_quote(quote: Quote):
    """Insert or update a quote."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO quotes (
            instrument_id, price, previous_close, quote_timestamp,
            fetched_at, provider, status, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instrument_id) DO UPDATE SET
            price = excluded.price,
            previous_close = excluded.previous_close,
            quote_timestamp = excluded.quote_timestamp,
            fetched_at = excluded.fetched_at,
            provider = excluded.provider,
            status = excluded.status,
            error_message = excluded.error_message
        """,
        (
            quote.instrument_id,
            _sql_value(quote.price),
            _sql_value(quote.previous_close),
            _sql_value(quote.quote_timestamp),
            _sql_value(quote.fetched_at),
            quote.provider,
            quote.status.value,
            quote.error_message,
        ),
    )
    conn.commit()
    conn.close()


def get_all_instruments():
    """Retrieve all active instruments as Instrument objects."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM instruments WHERE active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_instrument(row) for row in rows]


def get_instrument_by_ticker(ticker: str) -> Instrument | None:
    """Retrieve an instrument by its user_ticker."""
    if not ticker:
        return None
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM instruments WHERE user_ticker = ?", (ticker.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _row_to_instrument(row)
    return None


def get_quote_by_instrument_id(instrument_id: int) -> Quote | None:
    """Retrieve the latest quote for an instrument by instrument_id."""
    if not instrument_id:
        return None
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quotes WHERE instrument_id = ?", (instrument_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    from ..core.models import QuoteStatus
    try:
        raw_status = row["status"]
        if raw_status is None:
            status_enum = QuoteStatus.UNAVAILABLE
        elif isinstance(raw_status, int) or (isinstance(raw_status, str) and raw_status.isdigit()):
            status_enum = QuoteStatus(int(raw_status))
        elif str(raw_status) in QuoteStatus.__members__:
            status_enum = QuoteStatus[str(raw_status)]
        else:
            status_enum = QuoteStatus.UNAVAILABLE
    except (KeyError, ValueError):
        status_enum = QuoteStatus.UNAVAILABLE

    return Quote(
        id=row["id"],
        instrument_id=row["instrument_id"],
        price=_safe_decimal(row["price"]),
        previous_close=_safe_decimal(row["previous_close"]),
        quote_timestamp=_parse_date(row["quote_timestamp"]),
        fetched_at=_parse_date(row["fetched_at"]),
        provider=row["provider"] or "",
        status=status_enum,
        error_message=row["error_message"],
    )


def delete_instrument(ticker: str) -> bool:
    """Delete an instrument and its quotes by user_ticker."""
    if not ticker:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM instruments WHERE user_ticker = ?", (ticker.strip(),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    inst_id = row[0]
    cursor.execute("DELETE FROM quotes WHERE instrument_id = ?", (inst_id,))
    cursor.execute("DELETE FROM instruments WHERE id = ?", (inst_id,))
    conn.commit()
    conn.close()
    return True


def _parse_date(value):
    """Parse a date/DATETIME string from SQLite into a Python date.

    SQLite returns stored dates as strings; we convert only when the
    value is a non-empty string so the dataclass fields stay None for
    missing cells instead of raising.
    """
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _safe_decimal(value) -> Decimal | None:
    """Convert a possibly-None / string database value into Decimal or None.

    SQLite may return strings like "1.147,21" (Spanish thousands separator)
    in imported cells; this keeps those un-parsed so they do not silently
    become wrong numbers, and returns None when the cell is empty.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _row_to_instrument(row: sqlite3.Row) -> Instrument:
    """Convert one database row into an Instrument dataclass instance."""
    exchange = row["exchange"]
    if exchange:
        try:
            exchange_enum = Exchange(exchange.upper())
        except ValueError:
            exchange_enum = Exchange.UNKNOWN
    else:
        exchange_enum = Exchange.UNKNOWN

    keys = row.keys() if hasattr(row, "keys") else []
    return Instrument(
        id=row["id"],
        user_ticker=row["user_ticker"],
        provider_symbol=row["provider_symbol"],
        exchange=exchange_enum,
        currency=row["currency"],
        company_name=row["company_name"],
        analysis_date=_parse_date(row["analysis_date"]),
        analysis_reference_price=_safe_decimal(row["analysis_reference_price"]),
        start_of_year_date=_parse_date(row["start_of_year_date"]) if "start_of_year_date" in keys else None,
        start_of_year_price=_safe_decimal(row["start_of_year_price"]) if "start_of_year_price" in keys else None,
        target_price=_safe_decimal(row["target_price"]),
        comment=row["comment"] or "",
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
