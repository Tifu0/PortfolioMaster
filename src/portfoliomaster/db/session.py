"""Database engine and session management for watchlistTracker (WT)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from .schema import Base

_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker[Session]] = None


def is_production() -> bool:
    """Check if runtime environment is production."""
    return (
        os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
        or os.environ.get("RENDER", "").lower() == "true"
        or os.environ.get("NODE_ENV", "").lower() == "production"
    )


def get_database_url() -> str:
    """Retrieve normalized database URL from environment or fallback to SQLite for local dev.
    
    Fails fast in production if DATABASE_URL is missing, empty, or a placeholder.
    """
    raw_url = os.environ.get("DATABASE_URL")
    url = raw_url.strip() if raw_url else ""
    if url and not url.startswith("driver://") and url != "driver://user:pass@localhost/dbname":
        # Normalize postgres:// to postgresql:// for SQLAlchemy compatibility
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

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
    url = db_url or get_database_url()
    
    # Always create new engine if custom URL is provided or if none exists
    if db_url or _ENGINE is None:
        connect_args: dict = {}
        try:
            parsed_url = make_url(url)
            backend = parsed_url.get_backend_name()
            driver = parsed_url.get_driver_name()
        except Exception:
            backend = "sqlite" if url.startswith("sqlite") else "postgresql"
            driver = "psycopg2" if "+psycopg2" in url else "psycopg"

        if backend == "sqlite":
            connect_args["check_same_thread"] = False
        elif backend == "postgresql":
            # For PostgreSQL:
            # When using psycopg 3 (the default in SQLAlchemy 2.0 when psycopg is installed, or explicit +psycopg),
            # disable prepare_threshold for Supabase / PgBouncer / Supavisor connection poolers (port 6543 / Render).
            # In transaction pooling mode, prepared statements (_pg3_0) cause:
            #   psycopg.errors.InvalidSqlStatementName: prepared statement "_pg3_0" does not exist
            # Psycopg 2 does not support prepare_threshold and would error if passed.
            if driver == "psycopg2" or "+psycopg2" in url:
                pass
            else:
                connect_args["prepare_threshold"] = None
        else:
            pass

        engine_kwargs: dict = {
            "echo": echo,
            "connect_args": connect_args,
            "future": True,
        }
        if not url.startswith("sqlite"):
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

        engine = create_engine(url, **engine_kwargs)
        if not db_url:
            _ENGINE = engine
        return engine
    return _ENGINE


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Get or create sessionmaker factory."""
    global _SESSION_FACTORY
    eng = engine or get_engine()
    if engine or _SESSION_FACTORY is None:
        factory = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        if not engine:
            _SESSION_FACTORY = factory
        return factory
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


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    with session_scope() as session:
        yield session


def create_all_tables(engine: Optional[Engine] = None) -> None:
    """Create all declarative tables (used for tests and SQLite initialization)."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
