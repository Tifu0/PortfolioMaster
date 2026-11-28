import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from .connection import get_connection
from ..core.models import Quote, Instrument, Exchange, QuoteStatus


def _exchange_value(exchange) -> str:
    """Return the string value of an Exchange enum or a plain string."""
    if exchange is None:
        return Exchange.UNKNOWN.value
    if isinstance(exchange, Exchange):
        return exchange.value
    return str(exchange)


def _sql_value(value):
    """Convert values SQLite cannot bind natively (Decimal, date, datetime)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def wipe_database(db_path: Optional[str] = None):
    """Wipe all data from instruments and quotes."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quotes")
    cursor.execute("DELETE FROM instruments")
    conn.commit()
    conn.close()


_UPSERT_INSTRUMENT_SQL = """
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
        """


def _instrument_params(instrument: Instrument) -> tuple:
    return (
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
    )


def upsert_instrument(instrument: Instrument, db_path: Optional[str] = None):
    """Insert or update an instrument by user_ticker."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(_UPSERT_INSTRUMENT_SQL, _instrument_params(instrument))
        conn.commit()
    finally:
        conn.close()


def upsert_instruments_batch(instruments: List[Instrument], db_path: Optional[str] = None) -> int:
    """Insert or update a batch of instruments in a single SQLite transaction."""
    if not instruments:
        return 0
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.executemany(
            _UPSERT_INSTRUMENT_SQL,
            [_instrument_params(inst) for inst in instruments],
        )
        conn.commit()
        return len(instruments)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_instrument_by_id(instrument: Instrument, db_path: Optional[str] = None):
    """Update an instrument by its database primary key id."""
    if not instrument.id:
        return upsert_instrument(instrument, db_path=db_path)
    conn = get_connection(db_path)
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


def upsert_quote(quote: Quote, db_path: Optional[str] = None):
    """Insert or update a quote.

    CRITICAL FIX (Bug 3): Preserves existing valid price, previous_close, and
    quote_timestamp if the incoming quote has price=None (e.g. temporary provider failure).
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO quotes (
            instrument_id, price, previous_close, quote_timestamp,
            fetched_at, provider, status, error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instrument_id) DO UPDATE SET
            price = CASE WHEN excluded.price IS NOT NULL THEN excluded.price ELSE quotes.price END,
            previous_close = CASE WHEN excluded.previous_close IS NOT NULL THEN excluded.previous_close ELSE quotes.previous_close END,
            quote_timestamp = CASE WHEN excluded.quote_timestamp IS NOT NULL THEN excluded.quote_timestamp ELSE quotes.quote_timestamp END,
            fetched_at = excluded.fetched_at,
            provider = CASE WHEN excluded.provider != '' THEN excluded.provider ELSE quotes.provider END,
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


def get_all_instruments(include_inactive: bool = False, db_path: Optional[str] = None) -> List[Instrument]:
    """Retrieve instruments as Instrument objects."""
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if include_inactive:
        cursor.execute("SELECT * FROM instruments")
    else:
        cursor.execute("SELECT * FROM instruments WHERE active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_instrument(row) for row in rows]


def get_instrument_by_ticker(ticker: str, db_path: Optional[str] = None) -> Instrument | None:
    """Retrieve an instrument by its user_ticker."""
    if not ticker:
        return None
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM instruments WHERE user_ticker = ?", (ticker.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return _row_to_instrument(row)
    return None


def _parse_quote_status(raw_status) -> QuoteStatus:
    try:
        if raw_status is None:
            return QuoteStatus.UNAVAILABLE
        if isinstance(raw_status, int) or (isinstance(raw_status, str) and raw_status.isdigit()):
            return QuoteStatus(int(raw_status))
        if str(raw_status) in QuoteStatus.__members__:
            return QuoteStatus[str(raw_status)]
    except (KeyError, ValueError):
        pass
    return QuoteStatus.UNAVAILABLE


def get_all_instruments_with_quotes(
    include_inactive: bool = False, db_path: Optional[str] = None
) -> List[tuple[Instrument, Optional[Quote]]]:
    """Retrieve all instruments paired with their latest quotes in a single LEFT JOIN query."""
    conn = get_connection(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        sql = """
            SELECT
                i.*,
                q.id AS q_id,
                q.instrument_id AS q_instrument_id,
                q.price AS q_price,
                q.previous_close AS q_previous_close,
                q.quote_timestamp AS q_quote_timestamp,
                q.fetched_at AS q_fetched_at,
                q.provider AS q_provider,
                q.status AS q_status,
                q.error_message AS q_error_message
            FROM instruments i
            LEFT JOIN quotes q ON q.instrument_id = i.id
        """
        if not include_inactive:
            sql += " WHERE i.active = 1"
        cursor.execute(sql)
        rows = cursor.fetchall()
    finally:
        conn.close()

    results: List[tuple[Instrument, Optional[Quote]]] = []
    for row in rows:
        inst = _row_to_instrument(row)
        quote: Optional[Quote] = None
        if row["q_id"] is not None:
            quote = Quote(
                id=row["q_id"],
                instrument_id=row["q_instrument_id"],
                price=_safe_decimal(row["q_price"]),
                previous_close=_safe_decimal(row["q_previous_close"]),
                quote_timestamp=_parse_datetime(row["q_quote_timestamp"]),
                fetched_at=_parse_datetime(row["q_fetched_at"]),
                provider=row["q_provider"] or "",
                status=_parse_quote_status(row["q_status"]),
                error_message=row["q_error_message"],
            )
        results.append((inst, quote))
    return results


def get_quote_by_instrument_id(instrument_id: int, db_path: Optional[str] = None) -> Quote | None:
    """Retrieve the latest quote for an instrument by instrument_id."""
    if not instrument_id:
        return None
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quotes WHERE instrument_id = ?", (instrument_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    return Quote(
        id=row["id"],
        instrument_id=row["instrument_id"],
        price=_safe_decimal(row["price"]),
        previous_close=_safe_decimal(row["previous_close"]),
        quote_timestamp=_parse_datetime(row["quote_timestamp"]),
        fetched_at=_parse_datetime(row["fetched_at"]),
        provider=row["provider"] or "",
        status=_parse_quote_status(row["status"]),
        error_message=row["error_message"],
    )


def delete_instrument(ticker: str, db_path: Optional[str] = None) -> bool:
    """Delete an instrument and its quotes by user_ticker."""
    if not ticker:
        return False
    conn = get_connection(db_path)
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


def _parse_date(value) -> date | None:
    """Parse a date string from SQLite into a Python date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    val_str = str(value).strip()
    try:
        # Extract the date part if it contains time
        clean_part = val_str.split(" ")[0].split("T")[0]
        return date.fromisoformat(clean_part)
    except ValueError:
        return None


def _parse_datetime(value) -> datetime | None:
    """Parse a datetime/timestamp string from SQLite into a Python datetime (Bug 8 fix)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    val_str = str(value).strip()
    try:
        return datetime.fromisoformat(val_str)
    except ValueError:
        try:
            return datetime.strptime(val_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _safe_decimal(value) -> Decimal | None:
    """Convert a possibly-None / string database value into Decimal or None."""
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
