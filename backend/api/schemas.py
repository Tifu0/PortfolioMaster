"""Pydantic request and response schemas for watchlistTracker (WT) API."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class InstrumentCreate(BaseModel):
    user_ticker: str
    company_name: str = ""
    exchange: str = "AUTO"  # "AUTO" or Exchange enum
    currency: str = "EUR"
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None  # ISO date string (YYYY-MM-DD)
    start_of_year_price: Optional[float] = None
    start_of_year_date: Optional[str] = None  # ISO date string (YYYY-MM-DD)
    comment: str = ""
    fetch_yahoo: bool = True
    manual_price: Optional[float] = None
    manual_previous_close: Optional[float] = None


class InstrumentUpdate(BaseModel):
    new_ticker: Optional[str] = None
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None
    start_of_year_price: Optional[float] = None
    start_of_year_date: Optional[str] = None
    comment: Optional[str] = None
    active: Optional[bool] = None
    latest_price: Optional[float] = None
    previous_close: Optional[float] = None


class ImportInstrumentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_ticker: str = Field(..., min_length=1, max_length=30)
    provider_symbol: Optional[str] = None
    company_name: Optional[str] = ""
    exchange: Optional[str] = "UNKNOWN"
    currency: Optional[str] = "EUR"
    target_price: Optional[float] = None
    analysis_reference_price: Optional[float] = None
    analysis_date: Optional[str] = None
    start_of_year_price: Optional[float] = None
    start_of_year_date: Optional[str] = None
    comment: Optional[str] = ""
    active: Optional[bool] = True


class ImportConfirmRequest(BaseModel):
    instruments: List[ImportInstrumentItem]
