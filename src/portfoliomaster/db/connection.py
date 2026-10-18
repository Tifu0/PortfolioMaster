"""Database connection and schema management."""

from datetime import date, datetime
from decimal import Decimal
import sqlite3
import os
from ..core.config import DATABASE_FILENAME

sqlite3.register_adapter(Decimal, lambda value: format(value, "f"))
sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))

# Find the absolute path to the project root folder
# This file is in src/portfoliomaster/db/, so we go up 3 levels
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".."))
DB_PATH = os.path.join(PROJECT_ROOT, DATABASE_FILENAME)

def get_connection(db_path=None):
    """Get a connection to the SQLite database."""
    target = db_path or os.environ.get("PORTFOLIOMASTER_DB_PATH") or DB_PATH
    return sqlite3.connect(target)

def init_db():
    """Initialize database schema."""
    conn = get_connection()
    cursor = conn.cursor()
    # Basic schema as per plan 87-95
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_ticker TEXT UNIQUE NOT NULL,
            provider_symbol TEXT,
            exchange TEXT,
            currency TEXT,
            company_name TEXT,
            analysis_date DATE,
            analysis_reference_price DECIMAL,
            start_of_year_date DATE,
            start_of_year_price DECIMAL,
            target_price DECIMAL,
            comment TEXT,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration for existing databases that were created before start_of_year fields
    cursor.execute("PRAGMA table_info(instruments)")
    columns = [row[1] for row in cursor.fetchall()]
    if "start_of_year_date" not in columns:
        cursor.execute("ALTER TABLE instruments ADD COLUMN start_of_year_date DATE")
    if "start_of_year_price" not in columns:
        cursor.execute("ALTER TABLE instruments ADD COLUMN start_of_year_price DECIMAL")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument_id INTEGER NOT NULL UNIQUE,
            price DECIMAL,
            previous_close DECIMAL,
            quote_timestamp TIMESTAMP,
            fetched_at TIMESTAMP,
            provider TEXT,
            status TEXT,
            error_message TEXT,
            FOREIGN KEY (instrument_id) REFERENCES instruments (id)
        )
    """)
    conn.commit()
    conn.close()
