import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from .connection import get_connection
from .ports import instrument_to_dict, quote_to_dict
from ..core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)
from ..core.config import get_yahoo_suffix
from ..core.models import Exchange, Instrument, Quote, QuoteStatus
from ..core.parsing import (
    clean_opt_str,
    clean_str,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_decimal,
    parse_positive_decimal,
    safe_float,
)
from ..ingest.normalizer import normalize


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
    return parse_date(value)


def _parse_datetime(value) -> datetime | None:
    """Parse a datetime/timestamp string from SQLite into a Python datetime (Bug 8 fix)."""
    return parse_datetime(value)


def _safe_decimal(value) -> Decimal | None:
    """Convert a possibly-None / string database value into Decimal or None."""
    return parse_decimal(value)


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


class SqliteWatchlistStore:
    """PortfolioStore implementation backed by local SQLite (single-tenant)."""

    supports_sqlite_file_backups: bool = True

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def count_active_instruments(self) -> int:
        return len(get_all_instruments(include_inactive=False, db_path=self.db_path))

    def list_instruments(self, active_only: bool = True) -> List[dict]:
        instruments = get_all_instruments(include_inactive=not active_only, db_path=self.db_path)
        return [instrument_to_dict(inst) for inst in instruments]

    def get_instrument_detail(self, ticker: str) -> Optional[tuple[dict, Optional[dict]]]:
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            return None
        quote = get_quote_by_instrument_id(inst.id, db_path=self.db_path) if inst.id else None
        return instrument_to_dict(inst), quote_to_dict(quote)

    def instrument_exists(self, ticker: str) -> bool:
        return get_instrument_by_ticker(ticker, db_path=self.db_path) is not None

    def create_instrument(
        self,
        payload: dict,
        fetched_quote: Optional[Quote],
        manual_price: Optional[float],
        manual_previous_close: Optional[float] = None,
    ) -> tuple[dict, Optional[dict]]:
        ticker = str(payload["user_ticker"]).strip()
        if get_instrument_by_ticker(ticker, db_path=self.db_path):
            raise ValueError(f"Instrument with ticker '{ticker}' already exists in database.")

        exch_raw = payload.get("exchange", Exchange.UNKNOWN)
        if isinstance(exch_raw, Exchange):
            exchange = exch_raw
        else:
            try:
                exchange = Exchange(str(exch_raw).upper())
            except ValueError:
                exchange = Exchange.UNKNOWN

        inst = Instrument(
            user_ticker=ticker,
            provider_symbol=payload.get("provider_symbol"),
            exchange=exchange,
            currency=str(payload.get("currency") or "USD"),
            company_name=str(payload.get("company_name") or ticker),
            analysis_date=payload.get("analysis_date"),
            analysis_reference_price=payload.get("analysis_reference_price"),
            start_of_year_date=payload.get("start_of_year_date"),
            start_of_year_price=payload.get("start_of_year_price"),
            target_price=payload.get("target_price"),
            comment=str(payload.get("comment") or ""),
            active=bool(payload.get("active", True)),
        )
        upsert_instrument(inst, db_path=self.db_path)
        saved = get_instrument_by_ticker(ticker, db_path=self.db_path)

        quote_info: Optional[dict] = None
        if saved and saved.id:
            if manual_price is not None and manual_price > 0:
                now_utc = datetime.now(timezone.utc)
                q = Quote(
                    instrument_id=saved.id,
                    price=Decimal(str(manual_price)),
                    previous_close=(
                        Decimal(str(manual_previous_close))
                        if manual_previous_close and manual_previous_close > 0
                        else None
                    ),
                    quote_timestamp=now_utc,
                    fetched_at=now_utc,
                    provider="Manual",
                    status=QuoteStatus.FRESH,
                )
                upsert_quote(q, db_path=self.db_path)
                quote_info = {"source": "manual", "price": manual_price}
            elif fetched_quote is not None:
                fetched_quote.instrument_id = saved.id
                upsert_quote(fetched_quote, db_path=self.db_path)
                quote_info = {"source": "yahoo", "price": safe_float(fetched_quote.price)}

        return instrument_to_dict(saved or inst), quote_info

    def get_instrument_snapshot_for_update(self, ticker: str) -> Optional[dict]:
        """Read current instrument metadata needed to compute provider_symbol before update."""
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            return None
        return {
            "id": inst.id,
            "user_ticker": inst.user_ticker,
            "provider_symbol": inst.provider_symbol,
            "exchange": inst.exchange.value if hasattr(inst.exchange, "value") else inst.exchange,
            "currency": inst.currency,
        }

    def update_instrument(
        self,
        ticker: str,
        fields_set: set[str],
        updates: dict,
    ) -> dict:
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            raise KeyError(f"Instrument '{ticker}' not found")

        new_ticker = updates.get("new_ticker")
        if "new_ticker" in fields_set and new_ticker and new_ticker.strip().upper() != inst.user_ticker:
            new_t = new_ticker.strip().upper()
            existing = get_instrument_by_ticker(new_t, db_path=self.db_path)
            if existing and existing.id != inst.id:
                raise ValueError(
                    f"Cannot rename to '{new_t}': another instrument already uses that ticker."
                )
            inst.user_ticker = new_t

        if "currency" in fields_set and updates.get("currency") is not None:
            inst.currency = str(updates["currency"])
        if "exchange" in fields_set and updates.get("exchange") is not None:
            ex_raw = updates["exchange"]
            if isinstance(ex_raw, Exchange):
                inst.exchange = ex_raw
            else:
                try:
                    inst.exchange = Exchange(str(ex_raw).upper())
                except ValueError:
                    pass
        if "provider_symbol" in fields_set:
            inst.provider_symbol = updates.get("provider_symbol")
        if "company_name" in fields_set and updates.get("company_name") is not None:
            cn = str(updates["company_name"]).strip()
            inst.company_name = cn if cn else inst.user_ticker
        if "target_price" in fields_set:
            inst.target_price = updates.get("target_price")
        if "analysis_reference_price" in fields_set:
            inst.analysis_reference_price = updates.get("analysis_reference_price")
        if "analysis_date" in fields_set:
            inst.analysis_date = updates.get("analysis_date")
        if "start_of_year_price" in fields_set:
            inst.start_of_year_price = updates.get("start_of_year_price")
        if "start_of_year_date" in fields_set:
            inst.start_of_year_date = updates.get("start_of_year_date")
        if "comment" in fields_set:
            inst.comment = str(updates.get("comment") or "").strip()
        if "active" in fields_set and updates.get("active") is not None:
            inst.active = bool(updates["active"])

        update_instrument_by_id(inst, db_path=self.db_path)

        latest_price = updates.get("latest_price")
        if "latest_price" in fields_set and latest_price is not None and latest_price > 0 and inst.id:
            prev_close = updates.get("previous_close")
            now_utc = datetime.now(timezone.utc)
            q = Quote(
                instrument_id=inst.id,
                price=Decimal(str(latest_price)),
                previous_close=(
                    Decimal(str(prev_close))
                    if prev_close and prev_close > 0
                    else None
                ),
                quote_timestamp=now_utc,
                fetched_at=now_utc,
                provider="Manual",
                status=QuoteStatus.FRESH,
            )
            upsert_quote(q, db_path=self.db_path)
        elif updates.get("_rename_quote") is not None and inst.id:
            rq: Quote = updates["_rename_quote"]
            rq.instrument_id = inst.id
            upsert_quote(rq, db_path=self.db_path)

        return instrument_to_dict(inst)

    def delete_instrument(self, ticker: str) -> bool:
        return delete_instrument(ticker, db_path=self.db_path)

    def get_analysis_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]:
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            return None
        return inst.id, inst.user_ticker, inst.analysis_date, inst.provider_symbol

    def save_analysis_price(self, target_id: Any, price: Decimal, actual_date: date) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE instruments
                SET analysis_reference_price = ?, analysis_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (_sql_value(price), _sql_value(actual_date), int(target_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_ytd_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]:
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            return None
        return inst.id, inst.user_ticker, inst.start_of_year_date, inst.provider_symbol

    def save_ytd_price(self, target_id: Any, price: Decimal, actual_date: date) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE instruments
                SET start_of_year_price = ?, start_of_year_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (_sql_value(price), _sql_value(actual_date), int(target_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def list_missing_analysis_candidates(
        self,
    ) -> tuple[int, List[tuple[Any, str, date]], int]:
        active = get_all_instruments(include_inactive=False, db_path=self.db_path)
        candidates: List[tuple[Any, str, date]] = []
        missing_sym_failed = 0
        for inst in active:
            if inst.analysis_date and not inst.analysis_reference_price:
                if not inst.provider_symbol or not inst.id:
                    missing_sym_failed += 1
                else:
                    candidates.append((inst.id, inst.provider_symbol, inst.analysis_date))
        return len(active), candidates, missing_sym_failed

    def save_missing_analysis_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None:
        if not resolved:
            return
        conn = get_connection(self.db_path)
        try:
            conn.executemany(
                """
                UPDATE instruments
                SET analysis_reference_price = ?, analysis_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [(_sql_value(price), _sql_value(dt), int(rid)) for rid, price, dt in resolved],
            )
            conn.commit()
        finally:
            conn.close()

    def list_missing_ytd_candidates(self) -> tuple[int, List[tuple[Any, str]], int]:
        active = get_all_instruments(include_inactive=False, db_path=self.db_path)
        candidates: List[tuple[Any, str]] = []
        missing_sym_failed = 0
        for inst in active:
            if not inst.start_of_year_price:
                if not inst.provider_symbol or not inst.id:
                    missing_sym_failed += 1
                else:
                    candidates.append((inst.id, inst.provider_symbol))
        return len(active), candidates, missing_sym_failed

    def save_missing_ytd_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None:
        if not resolved:
            return
        conn = get_connection(self.db_path)
        try:
            conn.executemany(
                """
                UPDATE instruments
                SET start_of_year_price = ?, start_of_year_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                [(_sql_value(price), _sql_value(dt), int(rid)) for rid, price, dt in resolved],
            )
            conn.commit()
        finally:
            conn.close()

    def get_positions(self, active_only: bool = False) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT
                    i.*,
                    q.price          AS latest_price,
                    q.previous_close AS previous_close,
                    q.status         AS quote_status,
                    q.provider       AS quote_provider,
                    q.fetched_at     AS quote_fetched_at
                FROM instruments i
                LEFT JOIN quotes q ON q.instrument_id = i.id
            """
            if active_only:
                query += " WHERE i.active = 1"
            rows = conn.execute(query).fetchall()
        finally:
            conn.close()

        positions: List[dict] = []
        for row in rows:
            latest_price = safe_float(row["latest_price"])
            prev_close = safe_float(row["previous_close"])
            analysis_ref = safe_float(row["analysis_reference_price"])
            start_of_year_price = safe_float(row["start_of_year_price"])
            target = safe_float(row["target_price"])

            dv = daily_variation(latest_price, prev_close)
            vsa = variation_since_analysis(latest_price, analysis_ref)
            ytd = ytd_variation(latest_price, start_of_year_price)
            dtt = decline_to_target(target, latest_price)

            analysis_date_raw = row["analysis_date"]
            start_of_year_date_raw = row["start_of_year_date"]
            row_id = row["id"]
            try:
                row_id_int = int(row_id) if row_id is not None else None
            except (TypeError, ValueError):
                row_id_int = None

            row_active = row["active"]
            active_bool = bool(row_active) if row_active is not None else True

            positions.append(
                {
                    "id": row_id_int,
                    "user_ticker": clean_str(row["user_ticker"]),
                    "provider_symbol": clean_opt_str(row["provider_symbol"]),
                    "exchange": clean_str(row["exchange"]),
                    "currency": clean_str(row["currency"]),
                    "company_name": clean_str(row["company_name"]),
                    "analysis_date": str(analysis_date_raw) if analysis_date_raw is not None else None,
                    "analysis_reference_price": analysis_ref,
                    "start_of_year_date": str(start_of_year_date_raw) if start_of_year_date_raw is not None else None,
                    "start_of_year_price": start_of_year_price,
                    "target_price": target,
                    "comment": clean_str(row["comment"]),
                    "active": active_bool,
                    "latest_price": latest_price,
                    "previous_close": prev_close,
                    "quote_status": clean_opt_str(row["quote_status"]),
                    "quote_provider": clean_opt_str(row["quote_provider"]),
                    "quote_fetched_at": clean_opt_str(row["quote_fetched_at"]),
                    "daily_variation": safe_float(dv.daily_variation),
                    "daily_variation_valid": bool(dv.daily_variation_valid),
                    "variation_since_analysis": safe_float(vsa.variation_since_analysis),
                    "variation_since_analysis_valid": bool(vsa.variation_since_analysis_valid),
                    "ytd_variation": safe_float(ytd.ytd_variation),
                    "ytd_variation_valid": bool(ytd.ytd_variation_valid),
                    "decline_to_target": safe_float(dtt.decline_to_target),
                    "decline_to_target_valid": bool(dtt.decline_to_target_valid),
                }
            )
        return positions

    def get_metrics_rows(
        self,
    ) -> List[tuple[str, str, str, Optional[float], Optional[float]]]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    i.user_ticker,
                    i.company_name,
                    i.currency,
                    q.price AS latest_price,
                    q.previous_close AS previous_close
                FROM instruments i
                LEFT JOIN quotes q ON q.instrument_id = i.id
                """
            ).fetchall()
        finally:
            conn.close()

        return [
            (
                clean_str(ticker),
                clean_str(company) or clean_str(ticker),
                clean_str(curr),
                safe_float(latest_price),
                safe_float(prev_close),
            )
            for ticker, company, curr, latest_price, prev_close in rows
        ]

    def import_watchlist(
        self,
        items: List[dict],
        replace_all: bool = False,
        upsert_fn: Optional[Callable[[Instrument], Any]] = None,
    ) -> int:
        if replace_all:
            wipe_database(db_path=self.db_path)

        valid_instruments: List[Instrument] = []
        for inst_dict in items:
            ticker = str(inst_dict.get("user_ticker") or inst_dict.get("ticker") or "").strip()
            if not ticker:
                continue
            exchange_val = inst_dict.get("exchange", "UNKNOWN")
            try:
                exchange = Exchange(str(exchange_val))
            except ValueError:
                exchange = Exchange.UNKNOWN

            ref_dec = parse_positive_decimal(inst_dict.get("analysis_reference_price"))
            tgt_dec = parse_positive_decimal(inst_dict.get("target_price"))
            soy_dec = parse_positive_decimal(inst_dict.get("start_of_year_price"))

            analysis_dt = parse_date(inst_dict.get("analysis_date"))
            if ref_dec is not None and analysis_dt is None:
                analysis_dt = date.today()

            soy_dt = parse_date(inst_dict.get("start_of_year_date"))
            if soy_dec is not None and soy_dt is None:
                soy_dt = date(date.today().year, 1, 1)

            is_active = parse_bool(inst_dict.get("active", True), default=True, empty_as_false=True)
            valid_instruments.append(
                Instrument(
                    user_ticker=ticker,
                    provider_symbol=inst_dict.get("provider_symbol"),
                    exchange=exchange,
                    currency=str(inst_dict.get("currency") or ""),
                    company_name=str(inst_dict.get("company_name") or ticker),
                    analysis_date=analysis_dt,
                    analysis_reference_price=ref_dec,
                    start_of_year_date=soy_dt,
                    start_of_year_price=soy_dec,
                    target_price=tgt_dec,
                    comment=str(inst_dict.get("comment") or ""),
                    active=is_active,
                )
            )

        if not valid_instruments:
            return 0
        if upsert_fn is not None:
            for inst in valid_instruments:
                upsert_fn(inst)
            return len(valid_instruments)
        return upsert_instruments_batch(valid_instruments, db_path=self.db_path)

    def export_records(self) -> List[dict]:
        from ..backup.exporters import get_export_records

        return get_export_records(db_path=self.db_path)

    def wipe_all(self) -> None:
        wipe_database(db_path=self.db_path)

    def check_and_prepare_batch_refresh(
        self, now_utc: datetime, force: bool, stale_seconds: int
    ) -> dict:
        instruments = get_all_instruments(include_inactive=False, db_path=self.db_path)
        if not instruments:
            return {"state": "empty", "total_symbols": 0}

        for inst in instruments:
            norm_ticker, exchange = normalize(inst.user_ticker, inst.currency)
            suffix = get_yahoo_suffix(inst.user_ticker, exchange, inst.currency)
            expected = (
                f"{norm_ticker}{suffix}"
                if suffix and not norm_ticker.upper().endswith(suffix.upper())
                else norm_ticker
            )
            if inst.provider_symbol != expected or inst.exchange != exchange:
                inst.provider_symbol = expected
                inst.exchange = exchange
                upsert_instrument(inst, db_path=self.db_path)

        instrument_map: Dict[str, List[int]] = {}
        for inst in instruments:
            if inst.provider_symbol and inst.id:
                instrument_map.setdefault(inst.provider_symbol, []).append(inst.id)

        unique_symbols = list(instrument_map.keys())
        total_symbols = len(unique_symbols)

        stale_symbols: List[str] = []
        for sym, inst_ids in instrument_map.items():
            if force:
                stale_symbols.append(sym)
                continue
            needs_refresh = False
            for iid in inst_ids:
                q = get_quote_by_instrument_id(iid, db_path=self.db_path)
                if not q or q.fetched_at is None:
                    needs_refresh = True
                    break
                last_ts = q.fetched_at if q.fetched_at.tzinfo else q.fetched_at.replace(tzinfo=timezone.utc)
                if (now_utc - last_ts).total_seconds() >= stale_seconds:
                    needs_refresh = True
                    break
            if needs_refresh:
                stale_symbols.append(sym)

        if not stale_symbols:
            return {"state": "fresh", "total_symbols": total_symbols}

        return {
            "state": "ready",
            "run_id": None,
            "stale_symbols": stale_symbols,
            "total_symbols": total_symbols,
            "symbol_counts": {},
            "symbol_currencies": {},
            "existing_quote_symbols": set(),
            "instrument_map": instrument_map,
        }

    def persist_refresh_batch(
        self,
        run_id: Any,
        chunk_quotes: Dict[str, Quote],
        symbol_counts: Dict[str, int],
        symbol_currencies: Dict[str, str],
        existing_quote_symbols: set[str],
        instrument_map: Dict[str, List[int]],
        processed_count: int,
        updated: int,
        failed: int,
    ) -> tuple[int, int, int, int]:
        batch_updated = 0
        batch_failed = 0
        for symbol, quote in chunk_quotes.items():
            inst_ids = instrument_map.get(symbol, [])
            for inst_id in inst_ids:
                q_copy = Quote(
                    instrument_id=inst_id,
                    price=quote.price,
                    previous_close=quote.previous_close,
                    quote_timestamp=quote.quote_timestamp,
                    fetched_at=quote.fetched_at or datetime.now(timezone.utc),
                    provider=quote.provider,
                    status=quote.status,
                    error_message=quote.error_message,
                )
                upsert_quote(q_copy, db_path=self.db_path)

            if inst_ids:
                if quote.is_valid():
                    updated += len(inst_ids)
                    batch_updated += len(inst_ids)
                else:
                    failed += len(inst_ids)
                    batch_failed += len(inst_ids)
            processed_count += 1

        return processed_count, updated, failed, batch_updated

    def complete_refresh_run(
        self,
        run_id: Any,
        status: str,
        diagnostic_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        return None

    def get_active_refresh_run(self) -> Optional[dict]:
        return None

    def get_single_refresh_target(
        self,
        ticker: str,
        now_utc: datetime,
        force: bool,
        single_cooldown_seconds: int,
    ) -> Optional[dict]:
        inst = get_instrument_by_ticker(ticker, db_path=self.db_path)
        if not inst:
            return None

        symbol = inst.provider_symbol or inst.user_ticker
        saved_quote = get_quote_by_instrument_id(inst.id, db_path=self.db_path) if inst.id else None

        fresh_payload: Optional[dict] = None
        if not force and saved_quote and saved_quote.fetched_at:
            last_ts = saved_quote.fetched_at if saved_quote.fetched_at.tzinfo else saved_quote.fetched_at.replace(tzinfo=timezone.utc)
            if (now_utc - last_ts).total_seconds() < single_cooldown_seconds:
                fresh_payload = {
                    "status": "fresh",
                    "message": f"Cotización de {ticker} actualizada recientemente",
                    "refreshed_count": 0,
                    "ticker": ticker,
                    "price": safe_float(saved_quote.price),
                    "previous_close": safe_float(saved_quote.previous_close),
                    "analysis_reference_price": safe_float(inst.analysis_reference_price),
                    "start_of_year_price": safe_float(inst.start_of_year_price),
                    "provider": saved_quote.provider,
                    "quote_status": saved_quote.status.name if hasattr(saved_quote.status, "name") else str(saved_quote.status),
                    "quote": quote_to_dict(saved_quote),
                }

        return {
            "inst_id": inst.id,
            "inst": inst,
            "user_ticker": inst.user_ticker,
            "symbol": symbol,
            "analysis_date": inst.analysis_date,
            "analysis_reference_price": inst.analysis_reference_price,
            "start_of_year_price": inst.start_of_year_price,
            "fresh_payload": fresh_payload,
        }

    def save_single_refresh_result(
        self,
        target: dict,
        fetched_quote: Quote,
        resolved_analysis_price: Optional[Decimal],
        resolved_soy_price: Optional[Decimal],
        resolved_soy_date: Optional[date],
    ) -> dict:
        inst: Instrument = target["inst"]
        fetched_quote.instrument_id = inst.id
        if fetched_quote.fetched_at is None:
            fetched_quote.fetched_at = datetime.now(timezone.utc)
        upsert_quote(fetched_quote, db_path=self.db_path)

        changed_inst = False
        if resolved_analysis_price is not None:
            inst.analysis_reference_price = resolved_analysis_price
            changed_inst = True
        if resolved_soy_price is not None:
            inst.start_of_year_price = resolved_soy_price
            inst.start_of_year_date = resolved_soy_date
            changed_inst = True
        if changed_inst:
            update_instrument_by_id(inst, db_path=self.db_path)

        saved_quote = get_quote_by_instrument_id(inst.id, db_path=self.db_path) if inst.id else None
        return {
            "status": "ok",
            "ticker": target["user_ticker"],
            "price": safe_float(saved_quote.price) if saved_quote else None,
            "previous_close": safe_float(saved_quote.previous_close) if saved_quote else None,
            "analysis_reference_price": safe_float(inst.analysis_reference_price),
            "start_of_year_price": safe_float(inst.start_of_year_price),
            "provider": saved_quote.provider if saved_quote else None,
            "quote_status": (
                saved_quote.status.name
                if (saved_quote and hasattr(saved_quote.status, "name"))
                else (str(saved_quote.status) if saved_quote else None)
            ),
            "quote": quote_to_dict(saved_quote) if saved_quote else None,
        }

    def list_active_symbols(self) -> frozenset[str]:
        instruments = get_all_instruments(include_inactive=False, db_path=self.db_path)
        return frozenset(
            (inst.provider_symbol or inst.user_ticker or "").strip().upper()
            for inst in instruments
            if (inst.provider_symbol or inst.user_ticker or "").strip()
        )
