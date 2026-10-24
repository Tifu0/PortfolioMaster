"""Tests for scripts/migrate_sqlite_to_web.py CLI migration tool."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from portfoliomaster.db.schema import Base, MarketQuote, UserInstrument
from scripts.migrate_sqlite_to_web import (
    run_migration,
)


@pytest.fixture
def temp_legacy_sqlite():
    """Create a temporary legacy SQLite database with populated instruments and quotes."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_ticker TEXT UNIQUE NOT NULL,
            provider_symbol TEXT,
            exchange TEXT NOT NULL,
            currency TEXT NOT NULL,
            company_name TEXT NOT NULL,
            analysis_date TEXT,
            analysis_reference_price NUMERIC,
            start_of_year_date TEXT,
            start_of_year_price NUMERIC,
            target_price NUMERIC,
            comment TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER NOT NULL UNIQUE,
            price NUMERIC NOT NULL,
            previous_close NUMERIC,
            quote_timestamp TEXT,
            fetched_at TEXT,
            provider TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (instrument_id) REFERENCES instruments (id) ON DELETE CASCADE
        )
    """)
    # Insert 2 test instruments
    cur.execute("""
        INSERT INTO instruments (user_ticker, provider_symbol, exchange, currency, company_name, analysis_date, analysis_reference_price, start_of_year_date, start_of_year_price, target_price, comment, active)
        VALUES ('BME:VIS', 'VIS.MC', 'SPAIN', 'EUR', 'Viscofan S.A.', '2026-03-15', 55.456789, '2026-01-02', 52.123456, 70.000000, 'Quality packaging leader', 1)
    """)
    vis_id = cur.lastrowid
    cur.execute("""
        INSERT INTO quotes (instrument_id, price, previous_close, quote_timestamp, fetched_at, provider, status)
        VALUES (?, 58.750000, 58.200000, '2026-03-20T17:35:00', '2026-03-20T17:35:05', 'Yahoo', 'FRESH')
    """, (vis_id,))

    cur.execute("""
        INSERT INTO instruments (user_ticker, provider_symbol, exchange, currency, company_name, analysis_date, analysis_reference_price, start_of_year_date, start_of_year_price, target_price, comment, active)
        VALUES ('AAPL', 'AAPL', 'US', 'USD', 'Apple Inc.', '2026-02-10', 185.999999, '2026-01-02', 180.500000, 250.000000, 'Core tech holding', 1)
    """)
    aapl_id = cur.lastrowid
    cur.execute("""
        INSERT INTO quotes (instrument_id, price, previous_close, quote_timestamp, fetched_at, provider, status)
        VALUES (?, 210.350000, 208.100000, '2026-03-20T20:00:00', '2026-03-20T20:00:05', 'Yahoo', 'FRESH')
    """, (aapl_id,))

    conn.commit()
    conn.close()

    yield db_path

    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


@pytest.fixture
def temp_legacy_json():
    """Create a temporary legacy JSON backup file."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as tmp:
        data = {
            "version": "1.0",
            "exported_at": "2026-10-20T10:00:00",
            "total_positions": 2,
            "instruments": [
                {
                    "user_ticker": "LON:AZN",
                    "provider_symbol": "AZN.L",
                    "company_name": "AstraZeneca PLC",
                    "exchange": "UK",
                    "currency": "GBp",
                    "target_price": 12500.555,
                    "analysis_date": "2026-01-15",
                    "analysis_reference_price": 10500.123456,
                    "start_of_year_date": "2026-01-02",
                    "start_of_year_price": 10200.789012,
                    "comment": "Pharma defensiva",
                    "active": True,
                    "quote": {
                        "price": 11800.25,
                        "previous_close": 11750.0,
                        "quote_timestamp": "2026-03-20T16:30:00",
                        "fetched_at": "2026-03-20T16:30:05",
                        "provider": "Yahoo",
                        "status": "FRESH"
                    }
                },
                {
                    "user_ticker": "EPA:RMS",
                    "provider_symbol": "RMS.PA",
                    "company_name": "Hermes International",
                    "exchange": "FRANCE",
                    "currency": "EUR",
                    "target_price": 2400.0,
                    "analysis_date": "2026-02-01",
                    "analysis_reference_price": 2050.45,
                    "start_of_year_date": "2026-01-02",
                    "start_of_year_price": 1980.10,
                    "comment": "Luxury tier 1",
                    "active": False,
                    "quote": {
                        "price": 2150.0,
                        "previous_close": 2130.0,
                        "quote_timestamp": "2026-03-20T17:35:00",
                        "fetched_at": "2026-03-20T17:35:05",
                        "provider": "Yahoo",
                        "status": "FRESH"
                    }
                }
            ]
        }
        json.dump(data, tmp)
        json_path = Path(tmp.name)

    yield json_path

    if json_path.exists():
        try:
            json_path.unlink()
        except OSError:
            pass


@pytest.fixture
def target_web_db():
    """Create a temporary target database engine."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    yield db_url, engine

    engine.dispose()
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


def test_sqlite_migration_dry_run_does_not_commit(temp_legacy_sqlite, target_web_db):
    db_url, engine = target_web_db
    target_user_id = uuid.uuid4()

    summary = run_migration(
        source_sqlite=str(temp_legacy_sqlite),
        target_user_id_str=str(target_user_id),
        db_url=db_url,
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.input_instruments_count == 2
    assert summary.migrated_instruments_count == 2
    assert len(summary.payload_sha256) == 64

    # Verify that database remained empty due to rollback
    with sessionmaker(bind=engine)() as session:
        count = session.execute(select(UserInstrument)).scalars().all()
        assert len(count) == 0


def test_sqlite_migration_live_commit_and_precision(temp_legacy_sqlite, target_web_db):
    db_url, engine = target_web_db
    target_user_id = uuid.uuid4()

    summary = run_migration(
        source_sqlite=str(temp_legacy_sqlite),
        target_user_id_str=str(target_user_id),
        db_url=db_url,
        dry_run=False,
    )

    assert summary.dry_run is False
    assert summary.migrated_instruments_count == 2

    with sessionmaker(bind=engine)() as session:
        instruments = session.execute(
            select(UserInstrument).where(UserInstrument.user_id == target_user_id)
        ).scalars().all()
        assert len(instruments) == 2

        by_ticker = {i.user_ticker: i for i in instruments}
        assert "BME:VIS" in by_ticker
        assert "AAPL" in by_ticker

        vis = by_ticker["BME:VIS"]
        assert vis.provider_symbol == "VIS.MC"
        assert vis.company_name == "Viscofan S.A."
        # Verify exact Decimal precision (no float truncation)
        assert vis.analysis_reference_price == Decimal("55.456789")
        assert vis.start_of_year_price == Decimal("52.123456")
        assert vis.active is True

        # Verify decoupled market quote
        quote = session.execute(
            select(MarketQuote).where(MarketQuote.provider_symbol == "VIS.MC")
        ).scalar_one()
        assert quote.price == Decimal("58.750000")
        assert quote.status == "FRESH"


def test_json_migration_live_commit_and_isolation(temp_legacy_json, target_web_db):
    db_url, engine = target_web_db
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # Migrate into user_a
    summary_a = run_migration(
        source_json=str(temp_legacy_json),
        target_user_id_str=str(user_a),
        db_url=db_url,
        dry_run=False,
    )
    assert summary_a.migrated_instruments_count == 2

    # Verify user_a has instruments and user_b has none
    with sessionmaker(bind=engine)() as session:
        inst_a = session.execute(
            select(UserInstrument).where(UserInstrument.user_id == user_a)
        ).scalars().all()
        inst_b = session.execute(
            select(UserInstrument).where(UserInstrument.user_id == user_b)
        ).scalars().all()
        assert len(inst_a) == 2
        assert len(inst_b) == 0

        # Check RMS is inactive in user_a
        rms = next(i for i in inst_a if i.user_ticker == "EPA:RMS")
        assert rms.active is False
        assert rms.target_price == Decimal("2400.0")

        # Global market_quotes table has shared entry
        mq_azn = session.execute(
            select(MarketQuote).where(MarketQuote.provider_symbol == "AZN.L")
        ).scalar_one()
        assert mq_azn.price == Decimal("11800.25")


def test_migration_missing_user_raises(temp_legacy_sqlite, target_web_db):
    db_url, _ = target_web_db
    with pytest.raises(ValueError, match="Missing required target user ID"):
        run_migration(
            source_sqlite=str(temp_legacy_sqlite),
            target_user_id_str="",
            db_url=db_url,
        )


def test_migration_invalid_uuid_raises(temp_legacy_sqlite, target_web_db):
    db_url, _ = target_web_db
    with pytest.raises(ValueError, match="Invalid user ID format"):
        run_migration(
            source_sqlite=str(temp_legacy_sqlite),
            target_user_id_str="not-a-valid-uuid",
            db_url=db_url,
        )


def test_migration_unreachable_db_raises(temp_legacy_sqlite):
    target_user_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="Target database unreachable"):
        run_migration(
            source_sqlite=str(temp_legacy_sqlite),
            target_user_id_str=target_user_id,
            # connect_timeout=1 ensures test fails fast without hanging on network
            db_url="postgresql+psycopg://invalid_user:invalid_pass@127.0.0.1:59999/nonexistent_db?connect_timeout=1",
        )


def test_migration_duplicate_tickers_raises(target_web_db):
    db_url, _ = target_web_db
    target_user_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as tmp:
        data = {
            "version": "1.0",
            "instruments": [
                {"user_ticker": "AAPL", "company_name": "Apple Inc"},
                {"user_ticker": "AAPL", "company_name": "Apple Duplicate"},
            ]
        }
        json.dump(data, tmp)
        json_path = Path(tmp.name)

    try:
        with pytest.raises(ValueError, match="Pre-flight check failed: source JSON contains duplicate ticker"):
            run_migration(
                source_json=str(json_path),
                target_user_id_str=target_user_id,
                db_url=db_url,
            )
    finally:
        if json_path.exists():
            json_path.unlink()


def test_migration_orphan_quotes_in_sqlite_raises(target_web_db):
    db_url, _ = target_web_db
    target_user_id = str(uuid.uuid4())

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        orphan_db_path = Path(tmp.name)

    conn = sqlite3.connect(str(orphan_db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE instruments (
            id INTEGER PRIMARY KEY,
            user_ticker TEXT UNIQUE NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE quotes (
            id INTEGER PRIMARY KEY,
            instrument_id INTEGER,
            price NUMERIC
        )
    """)
    cur.execute("INSERT INTO instruments (id, user_ticker) VALUES (1, 'MSFT')")
    # Quote referencing non-existent instrument_id=999
    cur.execute("INSERT INTO quotes (id, instrument_id, price) VALUES (1, 999, 400.0)")
    conn.commit()
    conn.close()

    try:
        with pytest.raises(ValueError, match="orphan quote record"):
            run_migration(
                source_sqlite=str(orphan_db_path),
                target_user_id_str=target_user_id,
                db_url=db_url,
            )
    finally:
        if orphan_db_path.exists():
            orphan_db_path.unlink()


def test_rollback_user_migration(temp_legacy_sqlite, target_web_db):
    from scripts.migrate_sqlite_to_web import rollback_user_migration
    db_url, engine = target_web_db
    user_id = uuid.uuid4()

    # 1. Run live migration
    summary = run_migration(
        source_sqlite=str(temp_legacy_sqlite),
        target_user_id_str=str(user_id),
        db_url=db_url,
        dry_run=False,
    )
    assert summary.migrated_instruments_count == 2

    # Verify rows exist
    with sessionmaker(bind=engine)() as session:
        count = session.execute(
            select(UserInstrument).where(UserInstrument.user_id == user_id)
        ).scalars().all()
        assert len(count) == 2

    # 2. Rollback user migration
    deleted = rollback_user_migration(user_id=user_id, db_url=db_url)
    assert deleted == 2

    # Verify rows are removed
    with sessionmaker(bind=engine)() as session:
        count = session.execute(
            select(UserInstrument).where(UserInstrument.user_id == user_id)
        ).scalars().all()
        assert len(count) == 0


def test_alembic_upgrade_is_idempotent_and_non_destructive():
    import os
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from unittest.mock import patch

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    db_url = f"sqlite:///{db_path}"
    try:
        with patch.dict(os.environ, {"DATABASE_URL": db_url}):
            alembic_cfg = Config("alembic.ini")
            alembic_cfg.set_main_option("sqlalchemy.url", db_url)

            # 1. First upgrade on clean DB
            command.upgrade(alembic_cfg, "head")

            test_engine = create_engine(db_url)
            with test_engine.connect() as conn:
                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                assert "user_instruments" in tables
                assert "market_quotes" in tables
                assert "refresh_runs" in tables

            # 2. Second upgrade on already upgraded DB (proves idempotency and safety)
            command.upgrade(alembic_cfg, "head")

            with test_engine.connect() as conn:
                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                assert "user_instruments" in tables
                assert "market_quotes" in tables
                assert "refresh_runs" in tables
            test_engine.dispose()
    finally:
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass
