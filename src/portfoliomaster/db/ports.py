"""Unified persistence Protocol and canonical serialization helpers for PortfolioMaster."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ..core.models import Quote, QuoteStatus
from ..core.parsing import clean_str, safe_float


def instrument_to_dict(inst: Any) -> dict[str, object]:
    """Serialize Instrument dataclass, UserInstrument ORM row, or dictionary to canonical JSON dict."""
    if inst is None:
        return {}

    if isinstance(inst, dict):
        inst_id = inst.get("id")
        user_ticker = inst.get("user_ticker", "")
        provider_symbol = inst.get("provider_symbol")
        exchange_raw = inst.get("exchange", "")
        currency = inst.get("currency", "USD")
        company_name = inst.get("company_name", "")
        analysis_date = inst.get("analysis_date")
        analysis_price = inst.get("analysis_reference_price")
        soy_date = inst.get("start_of_year_date")
        soy_price = inst.get("start_of_year_price")
        target_price = inst.get("target_price")
        comment = inst.get("comment", "")
        active = inst.get("active", True)
        created_at = inst.get("created_at")
        updated_at = inst.get("updated_at")
    else:
        inst_id = getattr(inst, "id", None)
        user_ticker = getattr(inst, "user_ticker", "")
        provider_symbol = getattr(inst, "provider_symbol", None)
        exchange_raw = getattr(inst, "exchange", "")
        currency = getattr(inst, "currency", "USD")
        company_name = getattr(inst, "company_name", "")
        analysis_date = getattr(inst, "analysis_date", None)
        analysis_price = getattr(inst, "analysis_reference_price", None)
        soy_date = getattr(inst, "start_of_year_date", None)
        soy_price = getattr(inst, "start_of_year_price", None)
        target_price = getattr(inst, "target_price", None)
        comment = getattr(inst, "comment", "") or ""
        active = getattr(inst, "active", True)
        created_at = getattr(inst, "created_at", None)
        updated_at = getattr(inst, "updated_at", None)

    id_val: object = str(inst_id) if isinstance(inst_id, uuid.UUID) else inst_id
    exchange_val = exchange_raw.value if hasattr(exchange_raw, "value") else str(exchange_raw or "")
    an_dt = analysis_date.isoformat() if hasattr(analysis_date, "isoformat") else (str(analysis_date) if analysis_date else None)
    soy_dt = soy_date.isoformat() if hasattr(soy_date, "isoformat") else (str(soy_date) if soy_date else None)

    res: dict[str, object] = {
        "id": id_val,
        "user_ticker": user_ticker,
        "provider_symbol": provider_symbol,
        "exchange": exchange_val,
        "currency": currency,
        "company_name": company_name,
        "analysis_date": an_dt,
        "analysis_reference_price": safe_float(analysis_price),
        "start_of_year_date": soy_dt,
        "start_of_year_price": safe_float(soy_price),
        "target_price": safe_float(target_price),
        "comment": comment,
        "active": bool(active),
    }

    if created_at is not None:
        res["created_at"] = created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
    if updated_at is not None:
        res["updated_at"] = updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at)

    return res


def quote_to_dict(quote: Any) -> Optional[dict[str, object]]:
    """Serialize Quote dataclass, MarketQuote ORM row, or dictionary to canonical JSON dict."""
    if quote is None:
        return None

    if isinstance(quote, dict):
        return quote

    quote_id = getattr(quote, "id", None)
    inst_id = getattr(quote, "instrument_id", None)
    price = getattr(quote, "price", None)
    prev_close = getattr(quote, "previous_close", None)
    q_ts = getattr(quote, "quote_timestamp", None)
    fetched_at = getattr(quote, "fetched_at", None) or getattr(quote, "last_valid_fetched_at", None)
    provider = getattr(quote, "provider", "Yahoo") or "Yahoo"
    status_raw = getattr(quote, "status", None)
    status_str = (
        status_raw.name
        if isinstance(status_raw, QuoteStatus)
        else str(status_raw) if status_raw else "UNAVAILABLE"
    )
    error_msg = getattr(quote, "error_message", None)

    return {
        "id": quote_id,
        "instrument_id": inst_id,
        "price": safe_float(price),
        "previous_close": safe_float(prev_close),
        "quote_timestamp": q_ts.isoformat() if hasattr(q_ts, "isoformat") else (str(q_ts) if q_ts else None),
        "fetched_at": fetched_at.isoformat() if hasattr(fetched_at, "isoformat") else (str(fetched_at) if fetched_at else None),
        "provider": provider,
        "status": status_str,
        "error_message": error_msg,
    }


@runtime_checkable
class PortfolioStore(Protocol):
    """Unified persistence port implemented by SQLite and PostgreSQL multi-tenant adapters.

    Every method manages short, self-contained transactions so network I/O never runs
    while a database session or connection is held open.
    """

    supports_sqlite_file_backups: bool

    def count_active_instruments(self) -> int: ...

    def list_instruments(self, active_only: bool = True) -> List[dict]: ...

    def get_instrument_detail(self, ticker: str) -> Optional[tuple[dict, Optional[dict]]]: ...

    def instrument_exists(self, ticker: str) -> bool: ...

    def create_instrument(
        self,
        payload: dict,
        fetched_quote: Optional[Quote],
        manual_price: Optional[float],
        manual_previous_close: Optional[float] = None,
    ) -> tuple[dict, Optional[dict]]: ...

    def get_instrument_snapshot_for_update(self, ticker: str) -> Optional[dict]: ...

    def update_instrument(
        self,
        ticker: str,
        fields_set: set[str],
        updates: dict,
    ) -> dict: ...

    def delete_instrument(self, ticker: str) -> bool: ...

    def get_analysis_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]: ...

    def save_analysis_price(self, target_id: Any, price: Decimal, actual_date: date) -> None: ...

    def get_ytd_lookup_target(
        self, ticker: str
    ) -> Optional[tuple[Any, str, Optional[date], Optional[str]]]: ...

    def save_ytd_price(self, target_id: Any, price: Decimal, actual_date: date) -> None: ...

    def list_missing_analysis_candidates(
        self,
    ) -> tuple[int, List[tuple[Any, str, date]], int]: ...

    def save_missing_analysis_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None: ...

    def list_missing_ytd_candidates(self) -> tuple[int, List[tuple[Any, str]], int]: ...

    def save_missing_ytd_prices(
        self, resolved: List[tuple[Any, Decimal, date]]
    ) -> None: ...

    def get_positions(self, active_only: bool = False) -> List[dict]: ...

    def get_metrics_rows(
        self,
    ) -> List[tuple[str, str, str, Optional[float], Optional[float]]]: ...

    def import_watchlist(self, items: List[dict], replace_all: bool = False) -> int: ...

    def export_records(self) -> List[dict]: ...

    def wipe_all(self) -> None: ...

    def check_and_prepare_batch_refresh(
        self, now_utc: datetime, force: bool, stale_seconds: int
    ) -> dict: ...

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
    ) -> tuple[int, int, int, int]: ...

    def complete_refresh_run(
        self,
        run_id: Any,
        status: str,
        diagnostic_summary: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None: ...

    def get_active_refresh_run(self) -> Optional[dict]: ...

    def get_single_refresh_target(
        self,
        ticker: str,
        now_utc: datetime,
        force: bool,
        single_cooldown_seconds: int,
    ) -> Optional[dict]: ...

    def save_single_refresh_result(
        self,
        target: dict,
        fetched_quote: Quote,
        resolved_analysis_price: Optional[Decimal],
        resolved_soy_price: Optional[Decimal],
        resolved_soy_date: Optional[date],
    ) -> dict: ...

    def list_active_symbols(self) -> frozenset[str]: ...
