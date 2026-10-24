"""Multi-tenant Repository and Unit of Work for watchlistTracker (WT).

Guarantees tenant isolation by requiring explicit user_id and session
on every user-facing query or mutation. Decouples private user instruments
from globally shared market quotes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .schema import MarketQuote, RefreshRun, UserInstrument
from ..core.calculations import (
    daily_variation,
    decline_to_target,
    variation_since_analysis,
    ytd_variation,
)


def _parse_d(v: object) -> Optional[date]:
    """Safe parsing for dates from various string/date representations."""
    if not v:
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).split("T")[0].split(" ")[0].strip())
    except Exception:
        return None


def _parse_dec(v: object) -> Optional[Decimal]:
    """Safe parsing for Decimals from numeric or string values.
    
    Returns positive Decimal or None. DB constraints prohibit 0 or negative prices.
    """
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).strip())
        return d if d > 0 else None
    except Exception:
        return None


def _parse_bool(v: object) -> bool:
    """Safe parsing for boolean values."""
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    val_str = str(v).strip().lower()
    return val_str not in ("false", "0", "no", "f", "off")


class MultiTenantWatchlistRepository:
    """Repository strictly scoped to a single user_id for multi-tenant isolation."""

    def __init__(self, session: Session, user_id: uuid.UUID | str) -> None:
        self.session = session
        self.user_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))

    def get_instruments(self, active_only: bool = True) -> List[UserInstrument]:
        """Fetch all instruments belonging to the tenant."""
        stmt = select(UserInstrument).where(UserInstrument.user_id == self.user_id)
        if active_only:
            stmt = stmt.where(UserInstrument.active.is_(True))
        stmt = stmt.order_by(UserInstrument.user_ticker.asc())
        return list(self.session.scalars(stmt).unique().all())

    def get_instrument_by_ticker(self, ticker: str) -> Optional[UserInstrument]:
        """Fetch an instrument by user_ticker (case-insensitive) for this tenant."""
        if not ticker or not ticker.strip():
            return None
        clean_ticker = ticker.strip()
        stmt = select(UserInstrument).where(
            UserInstrument.user_id == self.user_id,
            func.upper(UserInstrument.user_ticker) == clean_ticker.upper(),
        )
        return self.session.scalars(stmt).first()

    def get_instrument_by_id(self, instrument_id: uuid.UUID | str) -> Optional[UserInstrument]:
        """Fetch an instrument by its UUID id for this tenant."""
        inst_uuid = instrument_id if isinstance(instrument_id, uuid.UUID) else uuid.UUID(str(instrument_id))
        stmt = select(UserInstrument).where(
            UserInstrument.user_id == self.user_id,
            UserInstrument.id == inst_uuid,
        )
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
        if "company_name" in fields_set and company_name is not None:
            inst.company_name = company_name

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
        Batch import or full JSON restore scoped strictly to this tenant.
        Mirrors Supabase RPC 'public.import_or_restore_user_watchlist'.
        """
        if replace_all:
            self.session.execute(
                delete(UserInstrument).where(UserInstrument.user_id == self.user_id)
            )
            self.session.flush()

        processed_count = 0
        for item in items:
            raw_ticker = item.get("user_ticker") or item.get("ticker")
            if not raw_ticker or not str(raw_ticker).strip():
                continue
            clean_ticker = str(raw_ticker).strip()

            raw_provider = item.get("provider_symbol")
            if not raw_provider or ":" in str(raw_provider):
                from portfoliomaster.ingest.normalizer import normalize
                from portfoliomaster.core.config import get_yahoo_suffix
                norm_sym, exch = normalize(clean_ticker, str(item.get("currency") or ""))
                suffix = get_yahoo_suffix(clean_ticker, exch, str(item.get("currency") or ""))
                if suffix and not norm_sym.upper().endswith(suffix.upper()):
                    norm_provider = f"{norm_sym}{suffix}".upper()
                else:
                    norm_provider = norm_sym.upper()
            else:
                norm_provider = str(raw_provider).strip().upper()

            # Ensure market_quote placeholder exists (mirrors trg_ensure_market_quote)
            if norm_provider:
                existing_quote = self.session.get(MarketQuote, norm_provider)
                if not existing_quote:
                    quote_entry = MarketQuote(
                        provider_symbol=norm_provider,
                        exchange=item.get("exchange") or "UNKNOWN",
                        currency=item.get("currency") or "EUR",
                        company_name=item.get("company_name") or clean_ticker,
                        status="UNAVAILABLE",
                    )
                    self.session.add(quote_entry)
                    self.session.flush()

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

            existing_inst = self.get_instrument_by_ticker(clean_ticker)
            if existing_inst:
                existing_inst.provider_symbol = norm_provider
                if item.get("exchange"):
                    existing_inst.exchange = item["exchange"]
                if item.get("currency"):
                    existing_inst.currency = item["currency"]
                if item.get("company_name"):
                    existing_inst.company_name = item["company_name"]
                if an_date is not None or "analysis_date" in item:
                    existing_inst.analysis_date = an_date
                if an_price is not None or "analysis_reference_price" in item:
                    existing_inst.analysis_reference_price = an_price
                if soy_date is not None or "start_of_year_date" in item:
                    existing_inst.start_of_year_date = soy_date
                if soy_price is not None or "start_of_year_price" in item:
                    existing_inst.start_of_year_price = soy_price
                if tgt_price is not None or "target_price" in item:
                    existing_inst.target_price = tgt_price
                if "comment" in item:
                    existing_inst.comment = str(item["comment"] or "")
                existing_inst.active = active_val
            else:
                new_inst = UserInstrument(
                    user_id=self.user_id,
                    user_ticker=clean_ticker,
                    provider_symbol=norm_provider,
                    exchange=item.get("exchange") or "UNKNOWN",
                    currency=item.get("currency") or "EUR",
                    company_name=item.get("company_name") or clean_ticker,
                    analysis_date=an_date,
                    analysis_reference_price=an_price,
                    start_of_year_date=soy_date,
                    start_of_year_price=soy_price,
                    target_price=tgt_price,
                    comment=str(item.get("comment") or ""),
                    active=active_val,
                )
                self.session.add(new_inst)

            processed_count += 1

        self.session.flush()
        return processed_count

    def delete_instrument(self, ticker: str) -> bool:
        """Delete instrument belonging to this tenant."""
        inst = self.get_instrument_by_ticker(ticker)
        if not inst:
            return False
        self.session.delete(inst)
        self.session.flush()
        return True

    def get_positions_with_calculations(self, active_only: bool = False) -> List[dict]:
        """
        Fetch positions joining private instruments with shared market quotes
        and calculate derived metrics using authoritative Decimal formulas.
        """
        instruments = self.get_instruments(active_only=active_only)
        positions = []

        for inst in instruments:
            quote = inst.quote

            latest_price = quote.price if quote else None
            prev_close = quote.previous_close if quote else None

            # Calculate metrics
            daily_res = daily_variation(latest_price, prev_close) if quote else None
            analysis_res = (
                variation_since_analysis(latest_price, inst.analysis_reference_price)
                if quote
                else None
            )
            ytd_res = ytd_variation(latest_price, inst.start_of_year_price) if quote else None
            target_res = decline_to_target(inst.target_price, latest_price) if quote else None

            pos_dict = {
                "id": str(inst.id),
                "user_ticker": inst.user_ticker,
                "provider_symbol": inst.provider_symbol,
                "exchange": inst.exchange,
                "currency": inst.currency,
                "company_name": inst.company_name or inst.user_ticker,
                "analysis_date": inst.analysis_date.isoformat() if inst.analysis_date else None,
                "analysis_reference_price": float(inst.analysis_reference_price) if inst.analysis_reference_price is not None else None,
                "start_of_year_date": inst.start_of_year_date.isoformat() if inst.start_of_year_date else None,
                "start_of_year_price": float(inst.start_of_year_price) if inst.start_of_year_price is not None else None,
                "target_price": float(inst.target_price) if inst.target_price is not None else None,
                "comment": inst.comment,
                "active": inst.active,
                # Market quote fields
                "latest_price": float(latest_price) if latest_price is not None else None,
                "previous_close": float(prev_close) if prev_close is not None else None,
                "quote_timestamp": quote.quote_timestamp.isoformat() if quote and quote.quote_timestamp else None,
                "quote_status": quote.status if quote else "UNAVAILABLE",
                "quote_provider": quote.provider if quote else "",
                "quote_fetched_at": quote.last_valid_fetched_at.isoformat() if quote and quote.last_valid_fetched_at else None,
                # Computed metrics
                "daily_variation": float(daily_res.daily_variation) if daily_res and daily_res.daily_variation_valid else None,
                "daily_variation_valid": daily_res.daily_variation_valid if daily_res else False,
                "variation_since_analysis": float(analysis_res.variation_since_analysis) if analysis_res and analysis_res.variation_since_analysis_valid else None,
                "variation_since_analysis_valid": analysis_res.variation_since_analysis_valid if analysis_res else False,
                "ytd_variation": float(ytd_res.ytd_variation) if ytd_res and ytd_res.ytd_variation_valid else None,
                "ytd_variation_valid": ytd_res.ytd_variation_valid if ytd_res else False,
                "decline_to_target": float(target_res.decline_to_target) if target_res and target_res.decline_to_target_valid else None,
                "decline_to_target_valid": target_res.decline_to_target_valid if target_res else False,
            }
            positions.append(pos_dict)

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

    def get_quotes_batch(self, symbols: List[str]) -> Dict[str, MarketQuote]:
        """Fetch quotes for a batch of symbols."""
        clean_symbols = [s.strip().upper() for s in symbols if s and s.strip()]
        if not clean_symbols:
            return {}
        stmt = select(MarketQuote).where(MarketQuote.provider_symbol.in_(clean_symbols))
        rows = self.session.scalars(stmt).all()
        return {q.provider_symbol: q for q in rows}

    def save_quote_success(
        self,
        symbol: str,
        price: Decimal,
        previous_close: Optional[Decimal] = None,
        quote_timestamp: Optional[datetime] = None,
        provider: str = "yahoo",
        status: str = "FRESH",
        company_name: Optional[str] = None,
        currency: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> MarketQuote:
        """Update or insert a successful quote observation."""
        canonical = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        quote = self.session.get(MarketQuote, canonical)

        if not quote:
            quote = MarketQuote(
                provider_symbol=canonical,
                currency=currency or "EUR",
                exchange=exchange or "UNKNOWN",
                company_name=company_name,
                provider=provider,
            )
            self.session.add(quote)

        # Update valid market values
        quote.price = price
        if previous_close is not None:
            quote.previous_close = previous_close
        if quote_timestamp is not None:
            quote.quote_timestamp = quote_timestamp
        quote.last_valid_fetched_at = now

        # Update attempt audit
        quote.last_attempt_at = now
        quote.status = status
        quote.error_message = None
        if company_name and not quote.company_name:
            quote.company_name = company_name

        self.session.flush()
        return quote

    def save_quote_failure(
        self,
        symbol: str,
        error_message: str,
        status: str = "ERROR",
        provider: str = "yahoo",
    ) -> MarketQuote:
        """
        Record a failed fetch attempt.
        CRITICAL FIX (Bug 3): Preserves existing valid price, previous_close, and quote_timestamp!
        """
        canonical = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        quote = self.session.get(MarketQuote, canonical)

        if not quote:
            quote = MarketQuote(
                provider_symbol=canonical,
                status=status,
                error_message=error_message,
                provider=provider,
                last_attempt_at=now,
            )
            self.session.add(quote)
        else:
            # Audit update only - existing price, previous_close, and timestamp remain untouched!
            quote.status = status
            quote.error_message = error_message
            quote.last_attempt_at = now

        self.session.flush()
        return quote

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

            quote.last_attempt_at = now
            quote.status = str(status).upper()
            quote.error_message = error_message
            if provider:
                quote.provider = provider

        self.session.flush()
        return quote


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


class UnitOfWork:
    """Unit of Work coordinator wrapping repositories in an atomic transaction."""

    def __init__(self, session: Session, user_id: Optional[uuid.UUID | str] = None) -> None:
        self.session = session
        self.user_id = user_id
        self._watchlist_repo: Optional[MultiTenantWatchlistRepository] = None
        self._quotes_repo: Optional[GlobalMarketQuotesRepository] = None
        self._refresh_repo: Optional[RefreshRunRepository] = None

    @property
    def watchlist(self) -> MultiTenantWatchlistRepository:
        if not self.user_id:
            raise ValueError("UnitOfWork requires a user_id to access the tenant watchlist repository.")
        if self._watchlist_repo is None:
            self._watchlist_repo = MultiTenantWatchlistRepository(self.session, self.user_id)
        return self._watchlist_repo

    @property
    def quotes(self) -> GlobalMarketQuotesRepository:
        if self._quotes_repo is None:
            self._quotes_repo = GlobalMarketQuotesRepository(self.session)
        return self._quotes_repo

    @property
    def refresh_runs(self) -> RefreshRunRepository:
        if self._refresh_repo is None:
            self._refresh_repo = RefreshRunRepository(self.session)
        return self._refresh_repo

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
