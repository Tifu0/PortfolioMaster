"""Multi-tenant Repository and Unit of Work for watchlistTracker (WT).

Guarantees tenant isolation by requiring explicit user_id and session
on every user-facing query or mutation. Decouples private user instruments
from globally shared market quotes.
"""

from __future__ import annotations

from collections import OrderedDict
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, noload

from . import session as db_session
from .ports import instrument_to_dict, quote_to_dict
from .schema import MarketQuote, RefreshRun, UserInstrument
from ..core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)
from ..core.models import Quote
from ..core.parsing import parse_bool, parse_date, parse_positive_decimal, safe_float


def _parse_d(v: object) -> Optional[date]:
    """Safe parsing for dates delegating to canonical core.parsing.parse_date."""
    return parse_date(v)


def _parse_dec(v: object) -> Optional[Decimal]:
    """Safe parsing for positive Decimals delegating to canonical core.parsing."""
    return parse_positive_decimal(v)


def _parse_bool(v: object) -> bool:
    """Safe parsing for boolean values delegating to canonical core.parsing."""
    return parse_bool(v, default=True)


# In-memory quote delta tracker to eliminate redundant database writes
# Bounded LRU mapping {canonical_symbol: (price, previous_close, status, earnings_date)}
MAX_DELTA_CACHE_ENTRIES = 2048
_LAST_KNOWN_QUOTES: OrderedDict[str, Tuple[Optional[Decimal], Optional[Decimal], str, Optional[date]]] = OrderedDict()
_DELTA_CACHE_LOCK = threading.Lock()


def clear_quote_delta_cache(symbols: Optional[Iterable[str]] = None) -> None:
    """Clear the in-memory quote cache globally or for a specific subset of symbols."""
    with _DELTA_CACHE_LOCK:
        if symbols is None:
            _LAST_KNOWN_QUOTES.clear()
        else:
            for sym in symbols:
                canonical = str(sym).strip().upper()
                if canonical:
                    _LAST_KNOWN_QUOTES.pop(canonical, None)


def filter_unchanged_quotes(quotes_data: List[dict]) -> List[dict]:
    """Filter out quotes whose price, previous_close, and status are identical to last known state.

    Prevents unnecessary writes to Supabase PostgreSQL when market prices have not moved
    (e.g. after-hours, weekends, closed exchanges, or unchanged stocks).
    """
    filtered = []
    with _DELTA_CACHE_LOCK:
        for item in quotes_data:
            canonical = str(item.get("provider_symbol", "")).strip().upper()
            if not canonical:
                continue
            raw_price = item.get("price")
            price = Decimal(str(raw_price)) if raw_price is not None and str(raw_price) != "" else None
            raw_prev = item.get("previous_close")
            prev_close = Decimal(str(raw_prev)) if raw_prev is not None and str(raw_prev) != "" else None
            status = str(item.get("status", "FRESH")).upper()
            earnings_dt = _parse_d(item.get("earnings_date"))

            last = _LAST_KNOWN_QUOTES.get(canonical)
            if last is not None:
                _LAST_KNOWN_QUOTES.move_to_end(canonical)
                last_price, last_prev, last_status, last_earnings = last
                if (
                    last_price == price
                    and last_prev == prev_close
                    and last_status == status
                    and last_earnings == earnings_dt
                ):
                    # Unchanged: skip DB write!
                    continue

            # Update bounded LRU cache and mark for persistence
            _LAST_KNOWN_QUOTES[canonical] = (price, prev_close, status, earnings_dt)
            _LAST_KNOWN_QUOTES.move_to_end(canonical)
            while len(_LAST_KNOWN_QUOTES) > MAX_DELTA_CACHE_ENTRIES:
                _LAST_KNOWN_QUOTES.popitem(last=False)
            filtered.append(item)
    return filtered



class MultiTenantWatchlistRepository:
    """Repository strictly scoped to a single user_id for multi-tenant isolation."""

    def __init__(self, session: Session, user_id: uuid.UUID | str) -> None:
        self.session = session
        self.user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

    def get_instruments(
        self, active_only: bool = True, include_quote: bool = False
    ) -> List[UserInstrument]:
        """Fetch all instruments belonging to the tenant."""
        stmt = select(UserInstrument).where(UserInstrument.user_id == self.user_id)
        if not include_quote:
            stmt = stmt.options(noload(UserInstrument.quote))
        if active_only:
            stmt = stmt.where(UserInstrument.active.is_(True))
        stmt = stmt.order_by(UserInstrument.user_ticker.asc())
        return list(self.session.scalars(stmt).unique().all())

    def get_instrument_by_ticker(
        self, ticker: str, include_quote: bool = True
    ) -> Optional[UserInstrument]:
        """Fetch an instrument by user_ticker (case-insensitive) for this tenant."""
        if not ticker or not ticker.strip():
            return None
        clean_ticker = ticker.strip()
        stmt = select(UserInstrument).where(
            UserInstrument.user_id == self.user_id,
            func.upper(UserInstrument.user_ticker) == clean_ticker.upper(),
        )
        if not include_quote:
            stmt = stmt.options(noload(UserInstrument.quote))
        return self.session.scalars(stmt).first()

    def create_instrument(
        self,
        user_ticker: str,
        provider_symbol: Optional[str] = None,
        exchange: str = "UNKNOWN",
        currency: str = "EUR",
        company_name: str = "",
        analysis_date: Optional[date] = None,
        analysis_reference_price: Optional[Decimal] = None,
        start_of_year_date: Optional[date] = None,
        start_of_year_price: Optional[Decimal] = None,
        target_price: Optional[Decimal] = None,
        comment: str = "",
        active: bool = True,
    ) -> UserInstrument:
        """Create a new watchlist instrument for this tenant."""
        clean_ticker = user_ticker.strip()
        norm_symbol = provider_symbol.strip().upper() if provider_symbol else clean_ticker.upper()
        if ":" in norm_symbol:
            from portfoliomaster.ingest.normalizer import normalize
            norm_sym, _ = normalize(norm_symbol, currency)
            norm_symbol = norm_sym.upper()

        # Ensure market_quotes entry exists for provider_symbol
        if norm_symbol:
            existing_quote = self.session.get(MarketQuote, norm_symbol)
            if not existing_quote:
                quote_entry = MarketQuote(
                    provider_symbol=norm_symbol,
                    currency=currency,
                    exchange=exchange,
                    company_name=company_name or clean_ticker,
                    status="UNAVAILABLE",
                    last_attempt_at=None,
                )
                self.session.add(quote_entry)
                self.session.flush()

        an_price = _parse_dec(analysis_reference_price)
        an_date = analysis_date
        if an_price is not None and an_date is None:
            an_date = date.today()

        soy_price = _parse_dec(start_of_year_price)
        soy_date = start_of_year_date
        if soy_price is not None and soy_date is None:
            soy_date = date(date.today().year, 1, 1)

        tgt_price = _parse_dec(target_price)

        inst = UserInstrument(
            user_id=self.user_id,
            user_ticker=clean_ticker,
            provider_symbol=norm_symbol,
            exchange=exchange,
            currency=currency,
            company_name=company_name or clean_ticker,
            analysis_date=an_date,
            analysis_reference_price=an_price,
            start_of_year_date=soy_date,
            start_of_year_price=soy_price,
            target_price=tgt_price,
            comment=comment or "",
            active=active,
        )
        self.session.add(inst)
        self.session.flush()
        return inst

    def update_instrument(
        self,
        ticker: str,
        fields_set: Set[str],
        new_ticker: Optional[str] = None,
        provider_symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        company_name: Optional[str] = None,
        analysis_date: Optional[date] = None,
        analysis_reference_price: Optional[Decimal] = None,
        start_of_year_date: Optional[date] = None,
        start_of_year_price: Optional[Decimal] = None,
        target_price: Optional[Decimal] = None,
        comment: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Optional[UserInstrument]:
        """
        Update instrument with strict tristate PATCH semantics.
        Fields omitted in fields_set are untouched; fields set to None are cleared to NULL.
        """
        inst = self.get_instrument_by_ticker(ticker)
        if not inst:
            return None

        if "new_ticker" in fields_set and new_ticker is not None:
            inst.user_ticker = new_ticker.strip()
        if "provider_symbol" in fields_set:
            inst.provider_symbol = provider_symbol.strip().upper() if provider_symbol else None
        if "exchange" in fields_set and exchange is not None:
            inst.exchange = exchange
        if "currency" in fields_set and currency is not None:
            inst.currency = currency
        if "company_name" in fields_set:
            inst.company_name = (
                company_name.strip() or None
                if isinstance(company_name, str)
                else company_name
            )

        # Nullable reference prices and dates (Bug 6 fix: explicit clearing supported)
        if "analysis_date" in fields_set:
            inst.analysis_date = analysis_date
        if "analysis_reference_price" in fields_set:
            inst.analysis_reference_price = analysis_reference_price
        if "start_of_year_date" in fields_set:
            inst.start_of_year_date = start_of_year_date
        if "start_of_year_price" in fields_set:
            inst.start_of_year_price = start_of_year_price
        if "target_price" in fields_set:
            inst.target_price = target_price
        if "comment" in fields_set:
            inst.comment = comment or ""
        if "active" in fields_set and active is not None:
            inst.active = active

        self.session.flush()
        return inst

    def import_or_restore_user_watchlist(
        self, items: List[dict], replace_all: bool = False
    ) -> int:
        """
        Batch import or full JSON restore scoped strictly to this tenant in O(1) round-trips.
        Mirrors Supabase RPC 'public.import_or_restore_user_watchlist'.
        """
        from portfoliomaster.core.config import get_yahoo_suffix
        from portfoliomaster.ingest.normalizer import normalize

        parsed_by_upper: Dict[str, dict] = {}
        processed_count = 0
        for item in items:
            raw_ticker = item.get("user_ticker") or item.get("ticker")
            if not raw_ticker or not str(raw_ticker).strip():
                continue
            clean_ticker = str(raw_ticker).strip()

            raw_provider = item.get("provider_symbol")
            if not raw_provider or ":" in str(raw_provider):
                norm_sym, exch = normalize(clean_ticker, str(item.get("currency") or ""))
                suffix = get_yahoo_suffix(clean_ticker, exch, str(item.get("currency") or ""))
                if suffix and not norm_sym.upper().endswith(suffix.upper()):
                    norm_provider = f"{norm_sym}{suffix}".upper()
                else:
                    norm_provider = norm_sym.upper()
            else:
                norm_provider = str(raw_provider).strip().upper()

            an_price = _parse_dec(item.get("analysis_reference_price"))
            an_date = _parse_d(item.get("analysis_date"))
            if an_price is not None and an_date is None:
                an_date = date.today()

            soy_price = _parse_dec(item.get("start_of_year_price"))
            soy_date = _parse_d(item.get("start_of_year_date"))
            if soy_price is not None and soy_date is None:
                soy_date = date(date.today().year, 1, 1)

            tgt_price = _parse_dec(item.get("target_price"))
            active_val = _parse_bool(item.get("active"))

            parsed_by_upper[clean_ticker.upper()] = {
                "clean_ticker": clean_ticker,
                "norm_provider": norm_provider,
                "exchange": item.get("exchange") or "UNKNOWN",
                "has_exchange": bool(item.get("exchange")),
                "currency": item.get("currency") or "EUR",
                "has_currency": bool(item.get("currency")),
                "company_name": item.get("company_name") or clean_ticker,
                "has_company_name": bool(item.get("company_name")),
                "an_date": an_date,
                "has_an_date": an_date is not None or "analysis_date" in item,
                "an_price": an_price,
                "has_an_price": an_price is not None or "analysis_reference_price" in item,
                "soy_date": soy_date,
                "has_soy_date": soy_date is not None or "start_of_year_date" in item,
                "soy_price": soy_price,
                "has_soy_price": soy_price is not None or "start_of_year_price" in item,
                "tgt_price": tgt_price,
                "has_tgt_price": tgt_price is not None or "target_price" in item,
                "comment": str(item.get("comment") or ""),
                "has_comment": "comment" in item,
                "active": active_val,
            }
            processed_count += 1

        if replace_all:
            self.session.execute(
                delete(UserInstrument).where(UserInstrument.user_id == self.user_id)
            )

        if not parsed_by_upper:
            self.session.flush()
            return 0

        # 1. Bulk insert missing market_quotes placeholders (ON CONFLICT DO NOTHING)
        quote_placeholders_map: Dict[str, dict] = {}
        now_utc = datetime.now(timezone.utc)
        for row in parsed_by_upper.values():
            sym = row["norm_provider"]
            if sym and sym not in quote_placeholders_map:
                quote_placeholders_map[sym] = {
                    "provider_symbol": sym,
                    "exchange": row["exchange"],
                    "currency": row["currency"],
                    "company_name": row["company_name"],
                    "provider": "yahoo",
                    "status": "UNAVAILABLE",
                    "created_at": now_utc,
                }

        if quote_placeholders_map:
            dialect_name = self.session.bind.dialect.name if self.session.bind is not None else "sqlite"
            ins_fn = pg_insert if dialect_name == "postgresql" else sqlite_insert
            quote_rows = list(quote_placeholders_map.values())
            for i in range(0, len(quote_rows), 200):
                chunk = quote_rows[i : i + 200]
                stmt = ins_fn(MarketQuote).values(chunk).on_conflict_do_nothing(
                    index_elements=["provider_symbol"]
                )
                self.session.execute(stmt)

        # 2. Preload existing tenant instruments in a single IN query when merging
        existing_by_upper: Dict[str, UserInstrument] = {}
        if not replace_all:
            upper_keys = list(parsed_by_upper.keys())
            existing_rows = self.session.scalars(
                select(UserInstrument)
                .options(noload(UserInstrument.quote))
                .where(
                    UserInstrument.user_id == self.user_id,
                    func.upper(UserInstrument.user_ticker).in_(upper_keys),
                )
            ).all()
            existing_by_upper = {inst.user_ticker.upper(): inst for inst in existing_rows}

        # 3. Partition into bulk updates and bulk inserts
        new_instruments: List[UserInstrument] = []
        for upper_key, row in parsed_by_upper.items():
            existing_inst = existing_by_upper.get(upper_key)
            if existing_inst is not None:
                existing_inst.provider_symbol = row["norm_provider"]
                if row["has_exchange"]:
                    existing_inst.exchange = row["exchange"]
                if row["has_currency"]:
                    existing_inst.currency = row["currency"]
                if row["has_company_name"]:
                    existing_inst.company_name = row["company_name"]
                if row["has_an_date"]:
                    existing_inst.analysis_date = row["an_date"]
                if row["has_an_price"]:
                    existing_inst.analysis_reference_price = row["an_price"]
                if row["has_soy_date"]:
                    existing_inst.start_of_year_date = row["soy_date"]
                if row["has_soy_price"]:
                    existing_inst.start_of_year_price = row["soy_price"]
                if row["has_tgt_price"]:
                    existing_inst.target_price = row["tgt_price"]
                if row["has_comment"]:
                    existing_inst.comment = row["comment"]
                existing_inst.active = row["active"]
            else:
                new_instruments.append(
                    UserInstrument(
                        user_id=self.user_id,
                        user_ticker=row["clean_ticker"],
                        provider_symbol=row["norm_provider"],
                        exchange=row["exchange"],
                        currency=row["currency"],
                        company_name=row["company_name"],
                        analysis_date=row["an_date"],
                        analysis_reference_price=row["an_price"],
                        start_of_year_date=row["soy_date"],
                        start_of_year_price=row["soy_price"],
                        target_price=row["tgt_price"],
                        comment=row["comment"],
                        active=row["active"],
                    )
                )

        if new_instruments:
            self.session.add_all(new_instruments)

        self.session.flush()
        return processed_count

    def delete_instrument(self, ticker: str) -> bool:
        """Delete instrument belonging to this tenant in a single DELETE ... RETURNING query."""
        if not ticker or not ticker.strip():
            return False
        clean_ticker = ticker.strip().upper()
        stmt = (
            delete(UserInstrument)
            .where(
                UserInstrument.user_id == self.user_id,
                func.upper(UserInstrument.user_ticker) == clean_ticker,
            )
            .returning(UserInstrument.id)
        )
        deleted_id = self.session.execute(stmt).scalar_one_or_none()
        return deleted_id is not None

    def get_positions_with_calculations(self, active_only: bool = False) -> List[dict]:
        """
        Fetch positions via lightweight column projection joining private instruments
        with shared market quotes and compute derived metrics using Decimal formulas.
        """
        stmt = (
            select(
                UserInstrument.id,
                UserInstrument.user_ticker,
                UserInstrument.provider_symbol,
                UserInstrument.exchange,
                UserInstrument.currency,
                UserInstrument.company_name,
                UserInstrument.analysis_date,
                UserInstrument.analysis_reference_price,
                UserInstrument.start_of_year_date,
                UserInstrument.start_of_year_price,
                UserInstrument.target_price,
                UserInstrument.comment,
                UserInstrument.active,
                MarketQuote.price,
                MarketQuote.previous_close,
                MarketQuote.quote_timestamp,
                MarketQuote.status,
                MarketQuote.provider,
                MarketQuote.last_valid_fetched_at,
                MarketQuote.earnings_date,
            )
            .outerjoin(
                MarketQuote,
                UserInstrument.provider_symbol == MarketQuote.provider_symbol,
            )
            .where(UserInstrument.user_id == self.user_id)
        )
        if active_only:
            stmt = stmt.where(UserInstrument.active.is_(True))
        stmt = stmt.order_by(UserInstrument.user_ticker.asc())

        rows = self.session.execute(stmt).all()
        positions = []
        for (
            inst_id,
            user_ticker,
            provider_symbol,
            exchange,
            currency,
            company_name,
            analysis_date,
            analysis_ref_price,
            soy_date,
            soy_price,
            target_price,
            comment,
            active,
            latest_price,
            prev_close,
            quote_timestamp,
            quote_status,
            quote_provider,
            last_valid_fetched_at,
            earnings_date,
        ) in rows:
            has_quote = quote_status is not None or latest_price is not None
            daily_res = daily_variation(latest_price, prev_close) if has_quote else None
            analysis_res = variation_since_analysis(latest_price, analysis_ref_price) if has_quote else None
            ytd_res = ytd_variation(latest_price, soy_price) if has_quote else None
            target_res = decline_to_target(target_price, latest_price) if has_quote else None

            positions.append(
                {
                    "id": str(inst_id),
                    "user_ticker": user_ticker,
                    "provider_symbol": provider_symbol,
                    "exchange": exchange,
                    "currency": currency,
                    "company_name": company_name or user_ticker,
                    "analysis_date": analysis_date.isoformat() if analysis_date else None,
                    "analysis_reference_price": float(analysis_ref_price) if analysis_ref_price is not None else None,
                    "start_of_year_date": soy_date.isoformat() if soy_date else None,
                    "start_of_year_price": float(soy_price) if soy_price is not None else None,
                    "target_price": float(target_price) if target_price is not None else None,
                    "comment": comment,
                    "active": active,
                    "latest_price": float(latest_price) if latest_price is not None else None,
                    "previous_close": float(prev_close) if prev_close is not None else None,
                    "quote_timestamp": quote_timestamp.isoformat() if quote_timestamp else None,
                    "quote_status": quote_status if quote_status is not None else "UNAVAILABLE",
                    "quote_provider": quote_provider if quote_provider is not None else "",
                    "quote_fetched_at": last_valid_fetched_at.isoformat() if last_valid_fetched_at else None,
                    "earnings_date": earnings_date.isoformat() if earnings_date else None,
                    "daily_variation": float(daily_res.daily_variation) if daily_res and daily_res.daily_variation_valid else None,
                    "daily_variation_valid": daily_res.daily_variation_valid if daily_res else False,
                    "variation_since_analysis": float(analysis_res.variation_since_analysis) if analysis_res and analysis_res.variation_since_analysis_valid else None,
                    "variation_since_analysis_valid": analysis_res.variation_since_analysis_valid if analysis_res else False,
                    "ytd_variation": float(ytd_res.ytd_variation) if ytd_res and ytd_res.ytd_variation_valid else None,
                    "ytd_variation_valid": ytd_res.ytd_variation_valid if ytd_res else False,
                    "decline_to_target": float(target_res.decline_to_target) if target_res and target_res.decline_to_target_valid else None,
                    "decline_to_target_valid": target_res.decline_to_target_valid if target_res else False,
                }
            )

        return positions


class GlobalMarketQuotesRepository:
    """Repository for global shared market quotes (accessible across tenants)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_quote(self, symbol: str) -> Optional[MarketQuote]:
        """Fetch quote by canonical provider symbol."""
        if not symbol:
            return None
        return self.session.get(MarketQuote, symbol.strip().upper())

    def upsert_market_quote_safe(
        self,
        provider_symbol: str,
        price: Optional[Decimal] = None,
        previous_close: Optional[Decimal] = None,
        quote_timestamp: Optional[datetime] = None,
        status: str = "FRESH",
        error_message: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
        company_name: Optional[str] = None,
        provider: str = "yahoo",
        earnings_date: Optional[date] = None,
    ) -> MarketQuote:
        """
        Non-destructive safe quote upsert strictly mirroring Supabase RPC
        'public.upsert_market_quote_safe'.
        
        If status in ('FRESH', 'DELAYED', 'STALE') and price > 0, updates the valid
        quote price, previous_close, quote_timestamp, and last_valid_fetched_at.
        If provider returned ERROR or UNAVAILABLE or price is None, existing market
        quote data remains intact and only last_attempt_at, status, and error_message
        are updated.
        """
        canonical = provider_symbol.strip().upper()
        now = datetime.now(timezone.utc)
        quote = self.session.get(MarketQuote, canonical)
        is_valid_price = (
            price is not None
            and price > 0
            and str(status).upper() in ("FRESH", "DELAYED", "STALE")
        )

        if not quote:
            quote = MarketQuote(
                provider_symbol=canonical,
                exchange=exchange or "UNKNOWN",
                currency=currency or "EUR",
                company_name=company_name,
                price=price if is_valid_price else None,
                previous_close=previous_close if (is_valid_price and previous_close and previous_close > 0) else None,
                quote_timestamp=quote_timestamp if is_valid_price else None,
                last_valid_fetched_at=now if is_valid_price else None,
                earnings_date=earnings_date,
                last_attempt_at=now,
                status=str(status).upper(),
                error_message=error_message,
                provider=provider,
            )
            self.session.add(quote)
        else:
            if exchange and exchange != "UNKNOWN":
                quote.exchange = exchange
            if currency:
                quote.currency = currency
            if company_name and not quote.company_name:
                quote.company_name = company_name

            if is_valid_price:
                quote.price = price
                if previous_close is not None and previous_close > 0:
                    quote.previous_close = previous_close
                if quote_timestamp is not None:
                    quote.quote_timestamp = quote_timestamp
                quote.last_valid_fetched_at = now
                if earnings_date is not None:
                    quote.earnings_date = earnings_date
                elif quote.earnings_date is not None and quote.earnings_date < now.date():
                    quote.earnings_date = None
            elif earnings_date is not None:
                quote.earnings_date = earnings_date

            quote.last_attempt_at = now
            quote.status = str(status).upper()
            quote.error_message = error_message
            if provider:
                quote.provider = provider

        self.session.flush()
        return quote

    def upsert_market_quotes_batch(
        self,
        quotes_data: List[dict],
        filter_deltas: bool = False,
    ) -> List[MarketQuote]:
        """High-performance zero-read batch upsert for quotes using native ON CONFLICT.

        Eliminates network pre-SELECTs and ORM merge overhead. Executes a single
        native SQL statement with ON CONFLICT (provider_symbol) DO UPDATE SET.
        Preserves existing valid price, previous_close, and quote_timestamp on error.
        """
        if not quotes_data:
            return []

        to_process = filter_unchanged_quotes(quotes_data) if filter_deltas else quotes_data
        if not to_process:
            return []

        now = datetime.now(timezone.utc)
        clean_params = []
        results: List[MarketQuote] = []

        for item in to_process:
            canonical = str(item.get("provider_symbol", "")).strip().upper()
            if not canonical:
                continue

            raw_price = item.get("price")
            price = Decimal(str(raw_price)) if raw_price is not None and str(raw_price) != "" else None
            raw_prev = item.get("previous_close")
            prev_close = (
                Decimal(str(raw_prev))
                if raw_prev is not None and str(raw_prev) != "" and Decimal(str(raw_prev)) > 0
                else None
            )
            status = str(item.get("status", "FRESH")).upper()
            error_message = item.get("error_message")
            exchange = item.get("exchange") or "UNKNOWN"
            currency = item.get("currency") or "EUR"
            company_name = item.get("company_name") or ""
            provider = item.get("provider") or "yahoo"

            is_valid_price = (
                price is not None
                and price > 0
                and status in ("FRESH", "DELAYED", "STALE")
            )

            q_ts = item.get("quote_timestamp")
            earnings_dt = _parse_d(item.get("earnings_date"))

            clean_params.append({
                "provider_symbol": canonical,
                "exchange": exchange,
                "currency": currency,
                "company_name": company_name,
                "provider": provider,
                "price": price if is_valid_price else None,
                "previous_close": prev_close if is_valid_price else None,
                "quote_timestamp": q_ts if is_valid_price else None,
                "last_valid_fetched_at": now if is_valid_price else None,
                "earnings_date": earnings_dt,
                "last_attempt_at": now,
                "status": status,
                "error_message": error_message,
                "created_at": now,
            })

            results.append(
                MarketQuote(
                    provider_symbol=canonical,
                    exchange=exchange,
                    currency=currency,
                    company_name=company_name,
                    provider=provider,
                    price=price if is_valid_price else None,
                    previous_close=prev_close if is_valid_price else None,
                    quote_timestamp=q_ts if is_valid_price else None,
                    earnings_date=earnings_dt,
                    status=status,
                    error_message=error_message,
                )
            )

        if not clean_params:
            return []

        upsert_sql = text("""
            INSERT INTO market_quotes (
                provider_symbol, exchange, currency, company_name, provider,
                price, previous_close, quote_timestamp, last_valid_fetched_at,
                earnings_date, last_attempt_at, status, error_message, created_at
            ) VALUES (
                :provider_symbol, :exchange, :currency, :company_name, :provider,
                :price, :previous_close, :quote_timestamp, :last_valid_fetched_at,
                :earnings_date, :last_attempt_at, :status, :error_message, :created_at
            )
            ON CONFLICT (provider_symbol) DO UPDATE SET
                exchange = CASE 
                    WHEN EXCLUDED.exchange IS NOT NULL AND EXCLUDED.exchange != 'UNKNOWN' THEN EXCLUDED.exchange 
                    ELSE market_quotes.exchange 
                END,
                currency = COALESCE(EXCLUDED.currency, market_quotes.currency),
                company_name = CASE 
                    WHEN (market_quotes.company_name IS NULL OR market_quotes.company_name = '') AND EXCLUDED.company_name IS NOT NULL AND EXCLUDED.company_name != '' THEN EXCLUDED.company_name 
                    ELSE market_quotes.company_name 
                END,
                provider = COALESCE(EXCLUDED.provider, market_quotes.provider),
                price = CASE 
                    WHEN EXCLUDED.price IS NOT NULL AND EXCLUDED.price > 0 THEN EXCLUDED.price 
                    ELSE market_quotes.price 
                END,
                previous_close = CASE 
                    WHEN EXCLUDED.price IS NOT NULL AND EXCLUDED.price > 0 AND EXCLUDED.previous_close IS NOT NULL AND EXCLUDED.previous_close > 0 THEN EXCLUDED.previous_close 
                    ELSE market_quotes.previous_close 
                END,
                quote_timestamp = CASE 
                    WHEN EXCLUDED.price IS NOT NULL AND EXCLUDED.price > 0 AND EXCLUDED.quote_timestamp IS NOT NULL THEN EXCLUDED.quote_timestamp 
                    ELSE market_quotes.quote_timestamp 
                END,
                last_valid_fetched_at = CASE 
                    WHEN EXCLUDED.price IS NOT NULL AND EXCLUDED.price > 0 THEN EXCLUDED.last_valid_fetched_at 
                    ELSE market_quotes.last_valid_fetched_at 
                END,
                earnings_date = CASE
                    WHEN EXCLUDED.earnings_date IS NOT NULL THEN EXCLUDED.earnings_date
                    WHEN EXCLUDED.price IS NOT NULL AND EXCLUDED.price > 0 AND market_quotes.earnings_date IS NOT NULL AND market_quotes.earnings_date < CURRENT_DATE THEN NULL
                    ELSE market_quotes.earnings_date
                END,
                last_attempt_at = EXCLUDED.last_attempt_at,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message
        """)

        self.session.execute(upsert_sql, clean_params)
        self.session.flush()
        self.session.expire_all()
        return results

    def touch_last_attempt_at(
        self, symbols: Iterable[str], attempted_at: Optional[datetime] = None
    ) -> int:
        """Update only last_attempt_at for symbols whose quote values were unchanged."""
        clean_syms = sorted(
            {str(s).strip().upper() for s in symbols if s and str(s).strip()}
        )
        if not clean_syms:
            return 0
        ts = attempted_at or datetime.now(timezone.utc)
        res = self.session.execute(
            update(MarketQuote)
            .where(MarketQuote.provider_symbol.in_(clean_syms))
            .values(last_attempt_at=ts)
        )
        self.session.flush()
        return int(res.rowcount or 0)


class RefreshRunRepository:
    """Repository for managing multi-worker / serverless batch executions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(
        self,
        total_symbols: int,
        trigger_type: str = "manual",
        user_id: Optional[uuid.UUID | str] = None,
    ) -> RefreshRun:
        """Create and start a new RefreshRun record."""
        run_uid = user_id if isinstance(user_id, uuid.UUID) else (uuid.UUID(str(user_id)) if user_id else None)
        run = RefreshRun(
            user_id=run_uid,
            trigger_type=trigger_type,
            status="RUNNING",
            total_symbols=total_symbols,
            processed_symbols=0,
            successful_symbols=0,
            failed_symbols=0,
            progress_percent=Decimal("0.00"),
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def update_progress(
        self,
        run_id: uuid.UUID,
        processed: int,
        successful: int,
        failed: int,
        current_symbol: Optional[str] = None,
    ) -> Optional[RefreshRun]:
        """Update live progress of a running execution."""
        run = self.session.get(RefreshRun, run_id)
        if not run:
            return None
        run.processed_symbols = processed
        run.successful_symbols = successful
        run.failed_symbols = failed
        run.current_symbol = current_symbol
        if run.total_symbols > 0:
            pct = (Decimal(processed) / Decimal(run.total_symbols)) * 100
            run.progress_percent = round(pct, 2)
        self.session.flush()
        return run

    def complete_run(
        self,
        run_id: uuid.UUID,
        status: str = "COMPLETED",
        diagnostic_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[RefreshRun]:
        """Mark a run as completed or failed."""
        run = self.session.get(RefreshRun, run_id)
        if not run:
            return None
        run.status = status
        run.diagnostic_summary = diagnostic_summary
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        self.session.flush()
        return run

    def is_running(self, scope: str = "GLOBAL", user_id: Optional[uuid.UUID | str] = None) -> bool:
        """Check if an active RUNNING execution exists for the given scope/tenant."""
        stmt = select(func.count(RefreshRun.id)).where(RefreshRun.status == "RUNNING")
        if scope == "USER" and user_id:
            uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
            stmt = stmt.where(RefreshRun.user_id == uid)
        count = self.session.scalar(stmt) or 0
        return count > 0

    def can_user_refresh(
        self, user_id: uuid.UUID | str, cooldown_seconds: int = 60
    ) -> Tuple[bool, Optional[str]]:
        """
        Check 60-second anti-spam cooldown and active running jobs for a user.
        Mirrors Supabase logic in request_user_refresh().
        """
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        stmt = (
            select(RefreshRun)
            .where(RefreshRun.user_id == uid)
            .order_by(RefreshRun.started_at.desc())
            .limit(1)
        )
        last_run = self.session.scalars(stmt).first()
        if last_run and last_run.status == "RUNNING":
            return False, "You already have a refresh in progress."

        if last_run and last_run.started_at:
            now = datetime.now(timezone.utc)
            last_ts = last_run.started_at if last_run.started_at.tzinfo else last_run.started_at.replace(tzinfo=timezone.utc)
            elapsed = (now - last_ts).total_seconds()
            if elapsed < cooldown_seconds:
                wait_sec = int(cooldown_seconds - elapsed)
                return False, f"Please wait {wait_sec} seconds before requesting another refresh."

        return True, None


class PostgresWatchlistStore:
    """PortfolioStore implementation backed by multi-tenant PostgreSQL (SQLAlchemy)."""

    supports_sqlite_file_backups: bool = False

    def __init__(self, user_id: Optional[uuid.UUID | str] = None) -> None:
        if user_id is None:
            self.user_id: Optional[uuid.UUID] = None
        elif isinstance(user_id, uuid.UUID):
            self.user_id = user_id
        else:
            self.user_id = uuid.UUID(str(user_id))

    def _require_user_id(self) -> uuid.UUID:
        if self.user_id is None:
            raise ValueError("user_id is required for tenant-scoped operations.")
        return self.user_id

    def count_active_instruments(self) -> int:
        with db_session.session_scope() as session:
            cnt = session.scalar(
                select(func.count()).select_from(UserInstrument).where(UserInstrument.active.is_(True))
            )
            return int(cnt or 0)

    def list_instruments(self, active_only: bool = True) -> List[dict]:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            instruments = repo.get_instruments(active_only=active_only, include_quote=False)
            return [instrument_to_dict(inst) for inst in instruments]

    def get_instrument_detail(self, ticker: str) -> Optional[tuple[dict, Optional[dict]]]:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            inst = repo.get_instrument_by_ticker(ticker, include_quote=True)
            if not inst:
                return None
            return instrument_to_dict(inst), quote_to_dict(inst.quote)

    def instrument_exists(self, ticker: str) -> bool:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            return repo.get_instrument_by_ticker(ticker, include_quote=False) is not None

    def create_instrument(
        self,
        payload: dict,
        fetched_quote: Optional[Quote],
        manual_price: Optional[float],
        manual_previous_close: Optional[float] = None,
    ) -> tuple[dict, Optional[dict]]:
        uid = self._require_user_id()
        ticker = str(payload["user_ticker"]).strip()
        exch_raw = payload.get("exchange", "UNKNOWN")
        exch_str = exch_raw.value if hasattr(exch_raw, "value") else str(exch_raw)
        provider_symbol = str(payload.get("provider_symbol") or ticker).strip().upper()
        currency = str(payload.get("currency") or "EUR")
        company_name = str(payload.get("company_name") or ticker)

        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            if repo.get_instrument_by_ticker(ticker, include_quote=False):
                raise ValueError(f"Instrument with ticker '{ticker}' already exists in database.")

            inst_created = repo.create_instrument(
                user_ticker=ticker,
                provider_symbol=provider_symbol,
                exchange=exch_str,
                currency=currency,
                company_name=company_name,
                analysis_date=payload.get("analysis_date"),
                analysis_reference_price=payload.get("analysis_reference_price"),
                start_of_year_date=payload.get("start_of_year_date"),
                start_of_year_price=payload.get("start_of_year_price"),
                target_price=payload.get("target_price"),
                comment=str(payload.get("comment") or ""),
                active=bool(payload.get("active", True)),
            )

            quote_info: Optional[dict] = None
            if manual_price is not None and manual_price > 0:
                quote_info = {"source": "manual", "price": manual_price}
            elif fetched_quote is not None:
                GlobalMarketQuotesRepository(session).upsert_market_quote_safe(
                    provider_symbol=provider_symbol,
                    price=fetched_quote.price,
                    previous_close=fetched_quote.previous_close,
                    quote_timestamp=fetched_quote.quote_timestamp,
                    status=(
                        fetched_quote.status.name
                        if hasattr(fetched_quote.status, "name")
                        else str(fetched_quote.status)
                    ),
                    error_message=fetched_quote.error_message,
                    exchange=inst_created.exchange,
                    currency=inst_created.currency,
                    company_name=company_name,
                    provider=fetched_quote.provider or "yahoo",
                    earnings_date=fetched_quote.earnings_date,
                )
                quote_info = {"source": "yahoo", "price": safe_float(fetched_quote.price)}

            return instrument_to_dict(inst_created), quote_info

    def get_instrument_snapshot_for_update(self, ticker: str) -> Optional[dict]:
        """Read current instrument metadata needed to compute provider_symbol before update."""
        uid = self._require_user_id()
        with db_session.get_session_factory()() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            inst = repo.get_instrument_by_ticker(ticker, include_quote=False)
            if not inst:
                return None
            return {
                "id": inst.id,
                "user_ticker": inst.user_ticker,
                "provider_symbol": inst.provider_symbol,
                "exchange": inst.exchange,
                "currency": inst.currency,
            }

    def update_instrument(
        self,
        ticker: str,
        fields_set: set[str],
        updates: dict,
    ) -> dict:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            inst = repo.get_instrument_by_ticker(ticker, include_quote=False)
            if not inst:
                raise KeyError(f"Instrument '{ticker}' not found")

            new_ticker_val = updates.get("new_ticker")
            if "new_ticker" in fields_set and new_ticker_val and new_ticker_val.strip().upper() != inst.user_ticker:
                new_t = new_ticker_val.strip().upper()
                existing = repo.get_instrument_by_ticker(new_t, include_quote=False)
                if existing and existing.id != inst.id:
                    raise ValueError(
                        f"Cannot rename to '{new_t}': another instrument already uses that ticker."
                    )
                new_ticker_val = new_t
            else:
                new_ticker_val = None

            exch_val = updates.get("exchange")
            if hasattr(exch_val, "value"):
                exch_val = exch_val.value

            updated = repo.update_instrument(
                ticker=ticker,
                fields_set=set(fields_set),
                new_ticker=new_ticker_val,
                provider_symbol=updates.get("provider_symbol"),
                exchange=exch_val,
                currency=updates.get("currency"),
                company_name=updates.get("company_name"),
                analysis_date=updates.get("analysis_date"),
                analysis_reference_price=updates.get("analysis_reference_price"),
                start_of_year_date=updates.get("start_of_year_date"),
                start_of_year_price=updates.get("start_of_year_price"),
                target_price=updates.get("target_price"),
                comment=updates.get("comment"),
                active=updates.get("active"),
            )
            if not updated:
                raise KeyError(f"Instrument '{ticker}' not found")

            provider_symbol_val = updated.provider_symbol
            if provider_symbol_val:
                mq = session.get(MarketQuote, provider_symbol_val)
                if not mq:
                    session.add(
                        MarketQuote(
                            provider_symbol=provider_symbol_val,
                            exchange=updated.exchange,
                            currency=updated.currency,
                            company_name=updated.company_name,
                            last_attempt_at=None,
                        )
                    )
            return instrument_to_dict(updated)

    def delete_instrument(self, ticker: str) -> bool:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            return repo.delete_instrument(ticker)

    def get_analysis_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]:
        uid = self._require_user_id()
        clean_ticker = ticker.strip()
        with db_session.session_scope() as session:
            row = session.execute(
                select(
                    UserInstrument.id,
                    UserInstrument.user_ticker,
                    UserInstrument.analysis_date,
                    UserInstrument.provider_symbol,
                ).where(
                    UserInstrument.user_id == uid,
                    func.upper(UserInstrument.user_ticker) == clean_ticker.upper(),
                )
            ).first()
            return tuple(row) if row else None  # type: ignore[return-value]

    def save_analysis_price(self, target_id: Any, price: Decimal, actual_date: date) -> None:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            session.execute(
                update(UserInstrument)
                .where(UserInstrument.id == target_id, UserInstrument.user_id == uid)
                .values(analysis_reference_price=price, analysis_date=actual_date)
            )

    def get_ytd_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]:
        uid = self._require_user_id()
        clean_ticker = ticker.strip()
        with db_session.session_scope() as session:
            row = session.execute(
                select(
                    UserInstrument.id,
                    UserInstrument.user_ticker,
                    UserInstrument.start_of_year_date,
                    UserInstrument.provider_symbol,
                ).where(
                    UserInstrument.user_id == uid,
                    func.upper(UserInstrument.user_ticker) == clean_ticker.upper(),
                )
            ).first()
            return tuple(row) if row else None  # type: ignore[return-value]

    def save_ytd_price(self, target_id: Any, price: Decimal, actual_date: date) -> None:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            session.execute(
                update(UserInstrument)
                .where(UserInstrument.id == target_id, UserInstrument.user_id == uid)
                .values(start_of_year_price=price, start_of_year_date=actual_date)
            )

    def list_missing_analysis_candidates(
        self,
    ) -> tuple[int, List[tuple[Any, str, date]], int]:
        if self.user_id is None:
            return 0, [], 0
        uid = self.user_id
        with db_session.session_scope() as session:
            rows = session.execute(
                select(
                    UserInstrument.id,
                    UserInstrument.provider_symbol,
                    UserInstrument.analysis_date,
                    UserInstrument.analysis_reference_price,
                ).where(
                    UserInstrument.user_id == uid,
                    UserInstrument.active.is_(True),
                )
            ).all()
        candidates: List[tuple[Any, str, date]] = []
        missing_sym_failed = 0
        for row_id, prov_sym, an_dt, an_price in rows:
            if an_dt and not an_price:
                if prov_sym:
                    candidates.append((row_id, prov_sym, an_dt))
                else:
                    missing_sym_failed += 1
        return len(rows), candidates, missing_sym_failed

    def save_missing_analysis_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None:
        if not resolved or self.user_id is None:
            return
        uid = self.user_id
        with db_session.session_scope() as session:
            for row_id, price_val, dt_val in resolved:
                session.execute(
                    update(UserInstrument)
                    .where(UserInstrument.id == row_id, UserInstrument.user_id == uid)
                    .values(analysis_reference_price=price_val, analysis_date=dt_val)
                )

    def list_missing_ytd_candidates(self) -> tuple[int, List[tuple[Any, str]], int]:
        if self.user_id is None:
            return 0, [], 0
        uid = self.user_id
        with db_session.session_scope() as session:
            rows = session.execute(
                select(
                    UserInstrument.id,
                    UserInstrument.provider_symbol,
                    UserInstrument.start_of_year_price,
                ).where(
                    UserInstrument.user_id == uid,
                    UserInstrument.active.is_(True),
                )
            ).all()
        candidates: List[tuple[Any, str]] = []
        missing_sym_failed = 0
        for row_id, prov_sym, soy_price in rows:
            if not soy_price:
                if prov_sym:
                    candidates.append((row_id, prov_sym))
                else:
                    missing_sym_failed += 1
        return len(rows), candidates, missing_sym_failed

    def save_missing_ytd_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None:
        if not resolved or self.user_id is None:
            return
        uid = self.user_id
        with db_session.session_scope() as session:
            for row_id, price_val, dt_val in resolved:
                session.execute(
                    update(UserInstrument)
                    .where(UserInstrument.id == row_id, UserInstrument.user_id == uid)
                    .values(start_of_year_price=price_val, start_of_year_date=dt_val)
                )

    def get_positions(self, active_only: bool = False) -> List[dict]:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            return repo.get_positions_with_calculations(active_only=active_only)

    def get_metrics_rows(
        self,
    ) -> List[tuple[str, str, str, Optional[float], Optional[float]]]:
        uid = self._require_user_id()
        rows_data: List[tuple[str, str, str, Optional[float], Optional[float]]] = []
        with db_session.session_scope() as session:
            stmt = (
                select(
                    UserInstrument.user_ticker,
                    UserInstrument.company_name,
                    UserInstrument.currency,
                    MarketQuote.price,
                    MarketQuote.previous_close,
                )
                .outerjoin(
                    MarketQuote,
                    UserInstrument.provider_symbol == MarketQuote.provider_symbol,
                )
                .where(UserInstrument.user_id == uid)
            )
            for ticker, company, curr, price, prev_close in session.execute(stmt).all():
                rows_data.append(
                    (
                        ticker,
                        company or ticker,
                        curr or "EUR",
                        float(price) if price is not None else None,
                        float(prev_close) if prev_close is not None else None,
                    )
                )
        return rows_data

    def import_watchlist(self, items: List[dict], replace_all: bool = False) -> int:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            return repo.import_or_restore_user_watchlist(items, replace_all=replace_all)

    def export_records(self) -> List[dict]:
        return self.get_positions(active_only=False)

    def wipe_all(self) -> None:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            session.execute(delete(UserInstrument).where(UserInstrument.user_id == uid))

    def check_and_prepare_batch_refresh(
        self, now_utc: datetime, force: bool, stale_seconds: int
    ) -> dict:
        run_id = None
        symbol_counts: Dict[str, int] = {}
        symbol_currencies: Dict[str, str] = {}
        stale_symbols: List[str] = []

        with db_session.session_scope() as session:
            run_repo = RefreshRunRepository(session)
            cutoff = now_utc - timedelta(minutes=10)
            try:
                stale_runs = session.scalars(
                    select(RefreshRun).where(
                        RefreshRun.status == "RUNNING",
                        RefreshRun.started_at < cutoff,
                    )
                ).all()
                for sr in stale_runs:
                    sr.status = "TIMEOUT"
                    sr.diagnostic_summary = "Timed out after 10 minutes without completion."
                if stale_runs:
                    session.flush()
            except Exception:
                pass

            if self.user_id is not None:
                can_rf, cooldown_msg = run_repo.can_user_refresh(
                    self.user_id, cooldown_seconds=stale_seconds
                )
                if not can_rf:
                    if cooldown_msg and "already have a refresh in progress" in cooldown_msg:
                        return {"state": "in_progress", "detail": cooldown_msg}
                    if not force:
                        return {"state": "fresh", "detail": cooldown_msg, "total_symbols": 0}
            elif run_repo.is_running(scope="GLOBAL"):
                return {
                    "state": "in_progress",
                    "detail": "Refresh is already in progress across instances.",
                }

            stmt = select(
                UserInstrument.provider_symbol,
                UserInstrument.user_ticker,
                UserInstrument.currency,
            ).where(UserInstrument.active.is_(True))
            if self.user_id is not None:
                stmt = stmt.where(UserInstrument.user_id == self.user_id)

            rows = session.execute(stmt).all()
            if not rows:
                return {"state": "empty", "total_symbols": 0}

            for prov_sym, usr_ticker, curr in rows:
                sym = (prov_sym or usr_ticker or "").strip().upper()
                if sym:
                    symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
                    if curr and sym not in symbol_currencies:
                        symbol_currencies[sym] = curr

            unique_symbols = list(symbol_counts.keys())
            total_symbols = len(unique_symbols)
            if force:
                clear_quote_delta_cache(symbols=unique_symbols)

            quotes_stmt = select(MarketQuote.provider_symbol, MarketQuote.last_attempt_at).where(
                MarketQuote.provider_symbol.in_(unique_symbols)
            )
            existing_attempts = {sym: last_at for sym, last_at in session.execute(quotes_stmt).all()}
            existing_quote_symbols = set(existing_attempts.keys())

            for sym in unique_symbols:
                if force:
                    stale_symbols.append(sym)
                    continue
                last_attempt = existing_attempts.get(sym)
                if last_attempt is None:
                    stale_symbols.append(sym)
                else:
                    last_ts = last_attempt if last_attempt.tzinfo else last_attempt.replace(tzinfo=timezone.utc)
                    if (now_utc - last_ts).total_seconds() >= stale_seconds:
                        stale_symbols.append(sym)

            if not stale_symbols:
                return {"state": "fresh", "total_symbols": total_symbols}

            try:
                run = run_repo.start_run(
                    total_symbols=len(stale_symbols),
                    trigger_type="manual" if self.user_id is not None else "batch_worker",
                    user_id=self.user_id,
                )
                run_id = run.id
            except Exception:
                pass

        return {
            "state": "ready",
            "run_id": run_id,
            "stale_symbols": stale_symbols,
            "total_symbols": total_symbols,
            "symbol_counts": symbol_counts,
            "symbol_currencies": symbol_currencies,
            "existing_quote_symbols": existing_quote_symbols,
            "instrument_map": {},
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
        batch_quotes_payload = []

        for sym, quote in chunk_quotes.items():
            status_str = quote.status.name if hasattr(quote.status, "name") else str(quote.status)
            batch_quotes_payload.append({
                "provider_symbol": sym,
                "price": quote.price,
                "previous_close": quote.previous_close,
                "quote_timestamp": quote.quote_timestamp,
                "status": status_str,
                "error_message": quote.error_message,
                "provider": quote.provider or "yahoo",
                "currency": symbol_currencies.get(sym, "EUR"),
                "earnings_date": quote.earnings_date,
            })
            cnt = symbol_counts.get(sym, 1)
            if quote.is_valid():
                updated += cnt
                batch_updated += cnt
            else:
                failed += cnt
                batch_failed += cnt
            processed_count += 1

        deltas_to_write = filter_unchanged_quotes(batch_quotes_payload)
        delta_syms = {d["provider_symbol"] for d in deltas_to_write}
        unchanged_existing_syms: list[str] = []
        for item in batch_quotes_payload:
            psym = item["provider_symbol"]
            if psym not in delta_syms:
                if psym in existing_quote_symbols:
                    unchanged_existing_syms.append(psym)
                else:
                    deltas_to_write.append(item)
                    existing_quote_symbols.add(psym)

        with db_session.session_scope() as batch_session:
            quotes_repo = GlobalMarketQuotesRepository(batch_session)
            if deltas_to_write:
                quotes_repo.upsert_market_quotes_batch(deltas_to_write)
                existing_quote_symbols.update(d["provider_symbol"] for d in deltas_to_write)
            if unchanged_existing_syms:
                quotes_repo.touch_last_attempt_at(unchanged_existing_syms, datetime.now(timezone.utc))
            if run_id:
                try:
                    RefreshRunRepository(batch_session).update_progress(
                        run_id=run_id,
                        processed=processed_count,
                        successful=updated,
                        failed=failed,
                    )
                except Exception:
                    pass

        return processed_count, updated, failed, batch_updated

    def complete_refresh_run(
        self,
        run_id: Any,
        status: str,
        diagnostic_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        if not run_id:
            return
        with db_session.session_scope() as session:
            RefreshRunRepository(session).complete_run(
                run_id=run_id,
                status=status,
                diagnostic_summary=diagnostic_summary,
                error_message=error_message,
            )

    def get_active_refresh_run(self) -> Optional[dict]:
        with db_session.get_session_factory()() as session:
            active_run = session.scalars(
                select(RefreshRun)
                .where(RefreshRun.status == "RUNNING")
                .order_by(RefreshRun.started_at.desc())
                .limit(1)
            ).first()
            if active_run is None:
                return None
            return {
                "is_refreshing": True,
                "processed_symbols": active_run.processed_symbols,
                "total_symbols": active_run.total_symbols,
            }

    def get_single_refresh_target(
        self,
        ticker: str,
        now_utc: datetime,
        force: bool,
        single_cooldown_seconds: int,
    ) -> Optional[dict]:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            repo = MultiTenantWatchlistRepository(session, uid)
            inst = repo.get_instrument_by_ticker(ticker)
            if not inst:
                return None

            symbol = (inst.provider_symbol or inst.user_ticker).strip().upper()
            quote = inst.quote
            fresh_payload: Optional[dict] = None
            if not force and quote and quote.last_attempt_at:
                last_ts = quote.last_attempt_at if quote.last_attempt_at.tzinfo else quote.last_attempt_at.replace(tzinfo=timezone.utc)
                if (now_utc - last_ts).total_seconds() < single_cooldown_seconds:
                    fresh_payload = {
                        "status": "fresh",
                        "message": f"Cotización de {ticker} actualizada recientemente",
                        "refreshed_count": 0,
                        "ticker": ticker,
                        "price": safe_float(quote.price),
                        "previous_close": safe_float(quote.previous_close),
                        "analysis_reference_price": safe_float(inst.analysis_reference_price),
                        "start_of_year_price": safe_float(inst.start_of_year_price),
                        "provider": quote.provider,
                        "quote_status": quote.status,
                        "quote": {
                            "price": safe_float(quote.price),
                            "previous_close": safe_float(quote.previous_close),
                            "status": quote.status,
                            "last_attempt_at": quote.last_attempt_at.isoformat() if quote.last_attempt_at else None,
                            "earnings_date": quote.earnings_date.isoformat() if quote.earnings_date else None,
                        },
                    }

            return {
                "inst_id": inst.id,
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
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            quotes_repo = GlobalMarketQuotesRepository(session)
            status_str = fetched_quote.status.name if hasattr(fetched_quote.status, "name") else str(fetched_quote.status)
            saved_quote = quotes_repo.upsert_market_quote_safe(
                provider_symbol=target["symbol"],
                price=fetched_quote.price,
                previous_close=fetched_quote.previous_close,
                quote_timestamp=fetched_quote.quote_timestamp,
                status=status_str,
                error_message=fetched_quote.error_message,
                provider=fetched_quote.provider or "yahoo",
                earnings_date=fetched_quote.earnings_date,
            )

            inst_updates: dict = {}
            if resolved_analysis_price is not None:
                inst_updates["analysis_reference_price"] = resolved_analysis_price
            if resolved_soy_price is not None:
                inst_updates["start_of_year_price"] = resolved_soy_price
                inst_updates["start_of_year_date"] = resolved_soy_date
            if inst_updates:
                session.execute(
                    update(UserInstrument)
                    .where(UserInstrument.id == target["inst_id"], UserInstrument.user_id == uid)
                    .values(**inst_updates)
                )

            final_an = resolved_analysis_price if resolved_analysis_price is not None else target["analysis_reference_price"]
            final_soy = resolved_soy_price if resolved_soy_price is not None else target["start_of_year_price"]
            return {
                "status": "ok",
                "ticker": target["user_ticker"],
                "price": safe_float(saved_quote.price),
                "previous_close": safe_float(saved_quote.previous_close),
                "analysis_reference_price": safe_float(final_an),
                "start_of_year_price": safe_float(final_soy),
                "provider": saved_quote.provider,
                "quote_status": saved_quote.status,
                "quote": {
                    "price": safe_float(saved_quote.price),
                    "previous_close": safe_float(saved_quote.previous_close),
                    "status": saved_quote.status,
                    "last_attempt_at": saved_quote.last_attempt_at.isoformat() if saved_quote.last_attempt_at else None,
                    "earnings_date": saved_quote.earnings_date.isoformat() if saved_quote.earnings_date else None,
                },
            }

    def list_active_symbols(self) -> frozenset[str]:
        uid = self._require_user_id()
        with db_session.session_scope() as session:
            rows = session.execute(
                select(UserInstrument.provider_symbol, UserInstrument.user_ticker).where(
                    UserInstrument.user_id == uid,
                    UserInstrument.active.is_(True),
                )
            ).all()
            return frozenset(
                (ps or ut or "").strip().upper()
                for ps, ut in rows
                if (ps or ut or "").strip()
            )
