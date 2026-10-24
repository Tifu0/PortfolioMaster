"""SQLAlchemy 2.0 declarative database schema for watchlistTracker (WT).

Defines the multi-tenant relational schema:
- UserInstrument: Tenant-isolated watchlist items (user_id scoped).
- MarketQuote: Global shared market data indexed by provider_symbol.
- RefreshRun: Persistent multi-worker / serverless execution audit record.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.types import TypeDecorator, CHAR


class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.
    Uses PostgreSQL's native UUID type, otherwise uses CHAR(36), storing as string.
    """
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value) if dialect.name != "postgresql" else value
        return str(uuid.UUID(str(value))) if dialect.name != "postgresql" else uuid.UUID(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class TZDateTime(TypeDecorator):
    """DateTime type that guarantees timezone-aware UTC datetime across SQLite and PostgreSQL."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value


def utc_now() -> datetime:
    """Helper for default timestamps in UTC."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all watchlistTracker declarative models."""
    pass


class MarketQuote(Base):
    """Global shared market quotes table.
    
    Decouples the latest valid market observation from the audit status
    of the most recent fetch attempt. One row per canonical provider_symbol.
    """
    __tablename__ = "market_quotes"

    # Canonical market symbol (e.g. 'AAPL', 'VIS.MC', 'MC.PA')
    provider_symbol: Mapped[str] = mapped_column(String(50), primary_key=True)

    # Market metadata
    currency: Mapped[str] = mapped_column(String(10), default="EUR", nullable=False)
    exchange: Mapped[str] = mapped_column(String(50), default="UNKNOWN", nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), default="yahoo", nullable=False)

    # Latest Valid Market Observation (Never overwritten by failed attempts)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    previous_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    quote_timestamp: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)
    last_valid_fetched_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)

    # Latest Fetch Attempt Audit
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        TZDateTime(), default=utc_now, nullable=True
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(
            "FRESH",
            "DELAYED",
            "STALE",
            "UNAVAILABLE",
            "ERROR",
            name="quote_status",
            native_enum=False,
            create_type=False,
        ),
        default="UNAVAILABLE",
        nullable=False,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utc_now, nullable=False)

    # Relationship to user instruments watching this symbol
    user_instruments: Mapped[List["UserInstrument"]] = relationship(
        "UserInstrument", back_populates="quote"
    )

    __table_args__ = (
        Index("idx_market_quotes_status_attempt", "status", "last_attempt_at"),
        Index("idx_market_quotes_last_attempt", "last_attempt_at"),
    )

    def is_valid(self) -> bool:
        """A quote is valid when it holds a positive market price."""
        return self.price is not None and self.price > 0


class UserInstrument(Base):
    """Private tenant-isolated watchlist item.
    
    Each row belongs to exactly one user_id. Tickers are ground-truth
    strings as entered by the user, linked optionally to a global MarketQuote.
    """
    __tablename__ = "user_instruments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    # User's display ticker (ground-truth string, preserved as written)
    user_ticker: Mapped[str] = mapped_column(String(50), nullable=False)

    # Normalized provider symbol reference
    provider_symbol: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("market_quotes.provider_symbol", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Instrument metadata
    exchange: Mapped[str] = mapped_column(String(50), default="UNKNOWN", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="EUR", nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), default="", nullable=True)

    # Reference prices and dates
    analysis_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    analysis_reference_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    start_of_year_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    start_of_year_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    target_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)

    # Notes and active flag
    comment: Mapped[Optional[str]] = mapped_column(Text, default="", nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationship to shared quote
    quote: Mapped[Optional[MarketQuote]] = relationship(
        "MarketQuote", back_populates="user_instruments", lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "user_ticker", name="uq_user_instruments_tenant_ticker"),
        Index("idx_user_instruments_tenant_active", "user_id", "active"),
        Index("idx_user_instruments_user_upper_ticker", "user_id", func.upper(text("user_ticker")), unique=True),
    )


class RefreshRun(Base):
    """Persistent audit and progress record of a refresh batch execution.
    
    Supports multi-worker / serverless architectures without in-memory state loss.
    """
    __tablename__ = "refresh_runs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), nullable=True, index=True)

    trigger_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", nullable=False, index=True)

    total_symbols: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_symbols: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_symbols: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_symbols: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    current_symbol: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    progress_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)

    diagnostic_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        Index("idx_refresh_runs_user_started", "user_id", "started_at"),
        Index("idx_refresh_runs_active", "status", "started_at"),
    )
