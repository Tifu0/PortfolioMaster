"""FastAPI dependency providers for market data and unified persistence seams."""

from __future__ import annotations

import uuid

from fastapi import Depends

from portfoliomaster.db.multi_tenant_repository import PostgresWatchlistStore
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.db.repository import SqliteWatchlistStore
from portfoliomaster.providers.yahoo_adapter import YahooAdapter

from .common import get_current_user_id, is_multi_tenant_db


def get_yahoo_provider() -> YahooAdapter:
    """Return a YahooAdapter instance (overridable via app.dependency_overrides)."""
    return YahooAdapter()


def get_portfolio_store(
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PortfolioStore:
    """Resolve the active tenant-scoped PortfolioStore (PostgreSQL or local SQLite)."""
    if is_multi_tenant_db():
        return PostgresWatchlistStore(user_id=user_id)
    return SqliteWatchlistStore()


def get_system_portfolio_store() -> PortfolioStore:
    """Resolve a system-level PortfolioStore for scheduler and public config checks."""
    if is_multi_tenant_db():
        return PostgresWatchlistStore(user_id=None)
    return SqliteWatchlistStore()
