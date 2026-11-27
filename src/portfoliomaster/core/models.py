"""Core data models for PortfolioMaster.

Pure Python data structures that hold the business facts: an instrument
(watchlist item), the latest quote state, and the result of a calculation.
No external dependencies and no network calls live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum, auto
from typing import Optional


class QuoteStatus(Enum):
    """How trustworthy the last observed quote is.

    Freshness is a first-class feature: a successful HTTP response does not
    prove the underlying market quote is current. See CLAUDE.md section 4.4.
    """

    # The quote timestamp matches the provider's current market data.
    FRESH = auto()
    # The quote is real-time on a market that is currently closed
    # (e.g. after-hours or end-of-day data). Usable but not live.
    DELAYED = auto()
    # The quote is older than the configured staleness threshold for this
    # market; treat it with caution.
    STALE = auto()
    # No price is available (market closed and no data, symbol not found).
    UNAVAILABLE = auto()
    # A fetch or parse error occurred; the database may hold a previous
    # valid value, which must be preserved and clearly marked.
    ERROR = auto()


class Exchange(Enum):
    """Known exchanges we import symbols for."""

    US = "US"
    SPAIN = "SPAIN"
    FRANCE = "FRANCE"
    UK = "UK"
    GERMANY = "GERMANY"
    ITALY = "ITALY"
    NETHERLANDS = "NETHERLANDS"
    BELGIUM = "BELGIUM"
    PORTUGAL = "PORTUGAL"
    SWITZERLAND = "SWITZERLAND"
    SWEDEN = "SWEDEN"
    DENMARK = "DENMARK"
    NORWAY = "NORWAY"
    FINLAND = "FINLAND"
    POLAND = "POLAND"
    AUSTRIA = "AUSTRIA"
    GREECE = "GREECE"
    IRELAND = "IRELAND"
    AUSTRALIA = "AUSTRALIA"
    SOUTH_KOREA = "SOUTH_KOREA"
    JAPAN = "JAPAN"
    HONG_KONG = "HONG_KONG"
    TAIWAN = "TAIWAN"
    CHINA = "CHINA"
    INDIA = "INDIA"
    CANADA = "CANADA"
    BRAZIL = "BRAZIL"
    MEXICO = "MEXICO"
    ARGENTINA = "ARGENTINA"
    SINGAPORE = "SINGAPORE"
    NEW_ZEALAND = "NEW_ZEALAND"
    TURKEY = "TURKEY"
    SAUDI_ARABIA = "SAUDI_ARABIA"
    INDONESIA = "INDONESIA"
    MALAYSIA = "MALAYSIA"
    THAILAND = "THAILAND"
    PHILIPPINES = "PHILIPPINES"
    UNKNOWN = "UNKNOWN"


@dataclass
class Instrument:
    """A watchlist item as the user owns it in the spreadsheet.

    user_ticker is never overwritten by normalization — it is the ground
    truth of what the user wrote. provider_symbol is the vendor-facing
    identifier when we know it; it may be None while unresolved.
    """

    id: Optional[int] = None
    user_ticker: str = ""
    provider_symbol: Optional[str] = None
    exchange: Exchange = Exchange.UNKNOWN
    currency: str = ""
    company_name: str = ""
    analysis_date: Optional[date] = None
    analysis_reference_price: Optional[Decimal] = None
    start_of_year_date: Optional[date] = None
    start_of_year_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    comment: str = ""
    active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if isinstance(self.created_at, date) and not isinstance(
            self.created_at, datetime
        ):
            self.created_at = datetime(self.created_at.year, self.created_at.month, self.created_at.day)
        if isinstance(self.updated_at, date) and not isinstance(
            self.updated_at, datetime
        ):
            self.updated_at = datetime(self.updated_at.year, self.updated_at.month, self.updated_at.day)


@dataclass
class Quote:
    """The latest valid quote state for an instrument.

    We store both the provider's quote timestamp (when the market data
    applies to) and our fetched timestamp (when we received it) so the UI
    can reason about freshness independently of the provider.
    """

    id: Optional[int] = None
    instrument_id: Optional[int] = None
    price: Optional[Decimal] = None
    previous_close: Optional[Decimal] = None
    quote_timestamp: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    provider: str = ""
    status: QuoteStatus = QuoteStatus.UNAVAILABLE
    error_message: Optional[str] = None

    def is_valid(self) -> bool:
        """A quote is valid when we actually have a price."""
        return self.price is not None and self.price > 0


@dataclass
class CalculationResult:
    """Container for all derived numbers plus metadata about validity.

    Each field carries its own validity flag so the UI can show
    "no data" instead of inventing a number. All amounts are Decimal.
    """

    daily_variation: Optional[Decimal] = None
    daily_variation_valid: bool = False
    variation_since_analysis: Optional[Decimal] = None
    variation_since_analysis_valid: bool = False
    ytd_variation: Optional[Decimal] = None
    ytd_variation_valid: bool = False
    decline_to_target: Optional[Decimal] = None
    decline_to_target_valid: bool = False
    price_valid: bool = False


@dataclass
class FreshnessConfig:
    """Rules that turn timestamp metadata into a QuoteStatus.

    Values are tuned to the provider and the markets we cover. A closed
    market returning end-of-day data is DELAYED, not ERROR.
    """

    delay_seconds: float = 60.0
    staleness_seconds: float = 2 * 24 * 60 * 60  # 2 days
    allow_delayed_alerts: bool = False  # never auto-alert on delayed data
    allow_stale_alerts: bool = False  # never auto-alert on stale data

    def freshness_state_naive(self, quote_timestamp: Optional[datetime]) -> QuoteStatus:
        """Same as freshness_state but tolerates naive timestamps."""
        if quote_timestamp is None:
            return QuoteStatus.UNAVAILABLE
        tz = quote_timestamp.tzinfo or datetime.now().astimezone().tzinfo
        age = (datetime.now(tz) - quote_timestamp.replace(tzinfo=tz)).total_seconds()
        if age <= self.delay_seconds:
            return QuoteStatus.FRESH
        if age <= self.staleness_seconds:
            return QuoteStatus.DELAYED
        return QuoteStatus.STALE
