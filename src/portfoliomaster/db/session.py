"""Database engine and session management for watchlistTracker (WT)."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .schema import Base

_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker[Session]] = None
_ENGINE_LOCK = threading.Lock()
_SESSION_FACTORY_LOCK = threading.Lock()


def is_production() -> bool:
    """Check if runtime environment is production."""
    return (
        os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
        or os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("NODE_ENV", "").lower() == "production"
    )


def normalize_database_url(url: str) -> str:
    """Select Psycopg 3 for generic and legacy PostgreSQL URLs."""
    scheme, separator, target = url.partition("://")
    if separator and scheme in ("postgres", "postgresql", "postgresql+psycopg2"):
        return f"postgresql+psycopg://{target}"
    return url


def psycopg_connect_args(url: str) -> dict[str, None]:
    """Disable prepared statements for compatibility with transaction poolers."""
    if url.startswith("postgresql+psycopg://"):
        return {"prepare_threshold": None}
    return {}


def get_database_url() -> str:
    """Retrieve normalized database URL from environment or fallback to SQLite for local dev.
    
    Fails fast in production if DATABASE_URL is missing, empty, or a placeholder.
    """
    raw_url = os.environ.get("DATABASE_URL")
    url = raw_url.strip() if raw_url else ""
    if url and not url.startswith("driver://") and url != "driver://user:pass@localhost/dbname":
        return normalize_database_url(url)

    if is_production():
        raise RuntimeError(
            "DATABASE_URL environment variable is required in production environment. "
            "Implicit fallback to SQLite is prohibited in production."
        )

    # Fallback to local SQLite path if defined
    sqlite_path = os.environ.get("PORTFOLIOMASTER_DB_PATH") or os.environ.get("WT_DB_PATH")
    if sqlite_path:
        return f"sqlite:///{sqlite_path}"

    return "sqlite:///portfolio.db"


def get_engine(db_url: Optional[str] = None, echo: bool = False) -> Engine:
    """Get or create singleton SQLAlchemy Engine with driver-safe connect_args."""
    global _ENGINE
    url = normalize_database_url(db_url) if db_url else get_database_url()

    if not db_url and _ENGINE is not None:
        return _ENGINE

    def _build_engine() -> Engine:
        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else psycopg_connect_args(url)
        engine_kwargs: dict = {
            "echo": echo,
            "connect_args": connect_args,
            "future": True,
        }
        if not is_sqlite:
            # Resilient connection pooling for Render & Supabase:
            # - pool_pre_ping: Tests connections with a ping query before checkout, purging broken sockets.
            # - pool_recycle: Recycles connections every 300s (5m) to stay ahead of cloud NAT / proxy timeouts.
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_recycle"] = int(os.environ.get("DB_POOL_RECYCLE", "300"))
            pool_size = os.environ.get("DB_POOL_SIZE")
            if pool_size:
                engine_kwargs["pool_size"] = int(pool_size)
            max_overflow = os.environ.get("DB_MAX_OVERFLOW")
            if max_overflow:
                engine_kwargs["max_overflow"] = int(max_overflow)
        return create_engine(url, **engine_kwargs)

    if db_url:
        return _build_engine()

    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = _build_engine()
        return _ENGINE


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Get or create sessionmaker factory (thread-safe singleton)."""
    global _SESSION_FACTORY
    if engine is not None:
        return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    if _SESSION_FACTORY is None:
        eng = get_engine()
        with _SESSION_FACTORY_LOCK:
            if _SESSION_FACTORY is None:
                _SESSION_FACTORY = sessionmaker(
                    bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
                )
    return _SESSION_FACTORY


@contextmanager
def session_scope(session_or_engine: Optional[Session | Engine] = None) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    if isinstance(session_or_engine, Session):
        yield session_or_engine
        return

    factory = get_session_factory(session_or_engine if isinstance(session_or_engine, Engine) else None)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
