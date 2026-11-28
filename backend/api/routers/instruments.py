"""Instruments CRUD and metadata resolution router for watchlistTracker (WT)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.ingest.normalizer import normalize
from portfoliomaster.providers.yahoo_adapter import (
    YahooAdapter,
    _create_ticker,
    resolve_company_name,
)

from ..common import get_current_user_id
from ..dependencies import (
    get_portfolio_store,
    get_system_portfolio_store,
    get_yahoo_provider,
)
from ..schemas import CheckYahooResponse, InstrumentCreate, InstrumentUpdate
from ..services import instrument_service

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _fetch_start_of_year_quote(
    provider_symbol: str, year: Optional[int] = None
) -> Optional[tuple[float, date]]:
    """Delegate start-of-year lookup to canonical YahooAdapter method."""
    return get_yahoo_provider().fetch_start_of_year_quote(provider_symbol, year)


def _fetch_historical_quote_and_date(
    provider_symbol: str, target_date: date, window_days: int = 10
) -> Optional[tuple[float, date]]:
    """Delegate historical lookup to canonical YahooAdapter method."""
    return get_yahoo_provider().fetch_historical_quote_and_date(
        provider_symbol, target_date, window_days=window_days
    )


def _fetch_historical_quote_for_date(provider_symbol: str, target_date: date) -> Optional[float]:
    """Delegate scalar historical lookup to canonical YahooAdapter method."""
    return get_yahoo_provider().fetch_historical_quote_for_date(provider_symbol, target_date)


def _resolve_missing_analysis_prices_sync(user_id: Optional[uuid.UUID] = None) -> dict:
    """Resolve missing analysis reference prices via PortfolioStore DI."""
    store = (
        get_portfolio_store(user_id=user_id)
        if user_id is not None
        else get_system_portfolio_store()
    )
    return instrument_service.resolve_missing_analysis_prices(
        store,
        get_yahoo_provider(),
        user_id=user_id,
        fetch_hist_fn=_fetch_historical_quote_and_date,
    )


def _resolve_missing_ytd_prices_sync(user_id: Optional[uuid.UUID] = None) -> dict:
    """Resolve missing YTD reference prices via PortfolioStore DI."""
    store = (
        get_portfolio_store(user_id=user_id)
        if user_id is not None
        else get_system_portfolio_store()
    )
    return instrument_service.resolve_missing_ytd_prices(
        store,
        get_yahoo_provider(),
        user_id=user_id,
        fetch_soy_fn=_fetch_start_of_year_quote,
    )


@router.get("")
def list_instruments(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """All active instruments (for dropdowns / selection)."""
    instruments = store.list_instruments(active_only=True)
    return {"instruments": instruments, "count": len(instruments)}


@router.get("/check-yahoo", response_model=CheckYahooResponse)
def check_yahoo_ticker(
    ticker: str,
    currency: Optional[str] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Check whether a ticker exists on Yahoo Finance and resolve its exchange/name."""
    return instrument_service.check_yahoo_ticker_metadata(
        ticker,
        currency,
        normalize_fn=normalize,
        create_ticker_fn=_create_ticker,
        resolve_name_fn=resolve_company_name,
    )


@router.get("/{ticker}")
def get_instrument(
    ticker: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Single instrument with its quote."""
    detail = store.get_instrument_detail(ticker)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found")
    instrument_dict, quote_dict = detail
    return {"instrument": instrument_dict, "quote": quote_dict}


@router.post("", status_code=201)
def create_instrument_endpoint(
    data: InstrumentCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Add a new instrument to the watchlist."""
    return instrument_service.create_instrument(
        data,
        user_id,
        store,
        provider,
        normalize_fn=normalize,
        resolve_name_fn=resolve_company_name,
        fetch_hist_fn=_fetch_historical_quote_and_date,
        fetch_soy_fn=_fetch_start_of_year_quote,
    )


@router.put("/{ticker}")
def update_instrument_endpoint(
    ticker: str,
    data: InstrumentUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Update instrument fields with strict tristate PATCH semantics."""
    return instrument_service.update_instrument(
        ticker,
        data,
        user_id,
        store,
        provider,
        normalize_fn=normalize,
    )


@router.delete("/{ticker}")
def delete_instrument_endpoint(
    ticker: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
):
    """Delete an instrument and its associated quote from the database."""
    return instrument_service.delete_instrument(ticker, user_id, store)


@router.post("/{ticker}/fetch-analysis-price")
def fetch_analysis_price_endpoint(
    ticker: str,
    target_date: Optional[str] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Fetch historical quote from Yahoo Finance for instrument's analysis_date."""
    return instrument_service.fetch_analysis_price(
        ticker,
        target_date,
        user_id,
        store,
        provider,
        fetch_hist_fn=_fetch_historical_quote_and_date,
    )


@router.post("/{ticker}/fetch-ytd-price")
def fetch_ytd_price_endpoint(
    ticker: str,
    target_year: Optional[int] = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Fetch start of year quote from Yahoo Finance for instrument for the given year."""
    return instrument_service.fetch_ytd_price(
        ticker,
        target_year,
        user_id,
        store,
        provider,
        fetch_soy_fn=_fetch_start_of_year_quote,
    )


@router.post("/resolve-missing-analysis-prices")
def resolve_missing_analysis_prices(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Batch resolve missing analysis reference prices for instruments having analysis_date."""
    return instrument_service.resolve_missing_analysis_prices(
        store,
        provider,
        user_id=user_id,
        fetch_hist_fn=_fetch_historical_quote_and_date,
    )


@router.post("/resolve-missing-ytd-prices")
def resolve_missing_ytd_prices(
    user_id: uuid.UUID = Depends(get_current_user_id),
    store: PortfolioStore = Depends(get_portfolio_store),
    provider: YahooAdapter = Depends(get_yahoo_provider),
):
    """Batch resolve missing start-of-year prices for instruments for the current year."""
    return instrument_service.resolve_missing_ytd_prices(
        store,
        provider,
        user_id=user_id,
        fetch_soy_fn=_fetch_start_of_year_quote,
    )
