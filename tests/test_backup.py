"""Unit tests for SQLite snapshot backups, automatic rotation, validation, and data exporters."""

from __future__ import annotations

import os
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from portfoliomaster.backup.exporters import (
    export_to_csv,
    export_to_excel,
    export_to_json,
    restore_from_json,
)
from portfoliomaster.backup.sqlite_backup import (
    create_automatic_safety_backup,
    create_sqlite_backup,
    list_automatic_backups,
    restore_automatic_backup,
    restore_sqlite_backup,
    validate_sqlite_backup,
)
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db.connection import init_db
from portfoliomaster.db.repository import (
    get_all_instruments,
    get_quote_by_instrument_id,
    upsert_instrument,
    upsert_quote,
    wipe_database,
)
from portfoliomaster.ingest.import_session import import_spreadsheet


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Set up an isolated database and backups directory for each test."""
    db_file = tmp_path / "test_portfolio.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", str(db_file))
    monkeypatch.setenv("PORTFOLIOMASTER_BACKUP_DIR", str(backup_dir))

    init_db()
    yield {"db_path": str(db_file), "backup_dir": str(backup_dir)}
    wipe_database()


class TestSqliteBackup:
    def test_create_and_validate_sqlite_backup(self, isolated_env):
        inst = Instrument(
            user_ticker="AAPL",
            company_name="Apple Inc.",
            exchange=Exchange.US,
            currency="USD",
            target_price=Decimal("200.00"),
        )
        upsert_instrument(inst)

        dest_backup = os.path.join(isolated_env["backup_dir"], "manual_backup.db")
        created_path = create_sqlite_backup(target_path=dest_backup)
        assert os.path.exists(created_path)
        assert os.path.getsize(created_path) > 0

        # Validate integrity and schema
        is_valid, err = validate_sqlite_backup(created_path)
        assert is_valid is True
        assert err is None

    def test_validate_sqlite_backup_failures(self, isolated_env, tmp_path):
        # 1. Non-existent file
        is_valid, err = validate_sqlite_backup(str(tmp_path / "nope.db"))
        assert is_valid is False
        assert "no existe" in err

        # 2. Empty file
        empty_file = tmp_path / "empty.db"
        empty_file.write_bytes(b"")
        is_valid, err = validate_sqlite_backup(str(empty_file))
        assert is_valid is False
        assert "vacío" in err

        # 3. Corrupt file (random bytes)
        corrupt_file = tmp_path / "corrupt.db"
        corrupt_file.write_bytes(b"THIS_IS_NOT_A_SQLITE_DATABASE_FILE")
        is_valid, err = validate_sqlite_backup(str(corrupt_file))
        assert is_valid is False

        # 4. Valid SQLite file without instruments table
        no_table_file = tmp_path / "no_table.db"
        conn = sqlite3.connect(str(no_table_file))
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        is_valid, err = validate_sqlite_backup(str(no_table_file))
        assert is_valid is False
        assert "instruments" in err

    def test_automatic_safety_backup_and_rotation(self, isolated_env):
        inst = Instrument(user_ticker="MSFT", company_name="Microsoft")
        upsert_instrument(inst)

        # Create 13 automatic backups
        created = []
        for i in range(13):
            # slightly staggered modification time or distinct reason
            b = create_automatic_safety_backup(reason=f"step_{i}")
            if b:
                created.append(b)

        # Verify rotation keeps only latest 10
        backups = list_automatic_backups()
        assert len(backups) <= 10

    def test_restore_sqlite_backup(self, isolated_env):
        # Insert initial instrument
        inst1 = Instrument(user_ticker="TSLA", company_name="Tesla Inc.")
        upsert_instrument(inst1)

        # Create snapshot
        backup_path = create_sqlite_backup()

        # Insert second instrument after snapshot
        inst2 = Instrument(user_ticker="AMZN", company_name="Amazon.com Inc.")
        upsert_instrument(inst2)
        assert len(get_all_instruments()) == 2

        # Restore from snapshot
        summary = restore_sqlite_backup(backup_path)
        assert summary["status"] == "ok"
        assert summary["restored_instruments"] == 1

        instruments = get_all_instruments()
        assert len(instruments) == 1
        assert instruments[0].user_ticker == "TSLA"

    def test_restore_automatic_backup_path_traversal(self, isolated_env):
        with pytest.raises(ValueError, match="no válido"):
            restore_automatic_backup("../../../etc/passwd.db")

        with pytest.raises(ValueError, match="no válido"):
            restore_automatic_backup("not_a_db.txt")


class TestExporters:
    def test_export_and_restore_json(self, isolated_env):
        inst = Instrument(
            user_ticker="SAN",
            company_name="Banco Santander",
            exchange=Exchange.SPAIN,
            currency="EUR",
            target_price=Decimal("5.50"),
            analysis_reference_price=Decimal("4.00"),
            analysis_date=date(2025, 5, 10),
            start_of_year_price=Decimal("4.20"),
            start_of_year_date=date(2026, 1, 2),
            comment="Dividendo atractivo",
            active=True,
        )
        upsert_instrument(inst)
        inserted = get_all_instruments()[0]

        quote = Quote(
            instrument_id=inserted.id,
            price=Decimal("4.80"),
            previous_close=Decimal("4.75"),
            provider="mock",
            status=QuoteStatus.FRESH,
        )
        upsert_quote(quote)

        # Export to JSON
        json_str = export_to_json()
        assert '"version": "1.0"' in json_str
        assert '"user_ticker": "SAN"' in json_str
        assert '"Dividendo atractivo"' in json_str

        # Wipe DB
        wipe_database()
        assert len(get_all_instruments()) == 0

        # Restore from JSON
        res = restore_from_json(json_str)
        assert res["status"] == "ok"
        assert res["restored_instruments"] == 1

        restored_list = get_all_instruments()
        assert len(restored_list) == 1
        restored = restored_list[0]
        assert restored.user_ticker == "SAN"
        assert restored.company_name == "Banco Santander"
        assert restored.target_price == Decimal("5.50")
        assert restored.analysis_reference_price == Decimal("4.00")
        assert restored.analysis_date == date(2025, 5, 10)
        assert restored.start_of_year_price == Decimal("4.20")
        assert restored.start_of_year_date == date(2026, 1, 2)
        assert restored.comment == "Dividendo atractivo"

        restored_quote = get_quote_by_instrument_id(restored.id)
        assert restored_quote is not None
        assert restored_quote.price == Decimal("4.80")
        assert restored_quote.status == QuoteStatus.FRESH

    def test_round_trip_csv_export_import(self, isolated_env, tmp_path):
        """CRITICAL: Test that exported CSV can be imported with 100% field preservation."""
        inst = Instrument(
            user_ticker="RMS.PA",
            company_name="Hermes International",
            exchange=Exchange.FRANCE,
            currency="EUR",
            target_price=Decimal("2400.00"),
            analysis_reference_price=Decimal("2000.00"),
            analysis_date=date(2024, 3, 15),
            start_of_year_price=Decimal("1950.50"),
            start_of_year_date=date(2026, 1, 2),
            comment="Sector lujo líder con altos márgenes",
            active=True,
        )
        upsert_instrument(inst)

        csv_str = export_to_csv()
        assert "Ticker" in csv_str
        assert "Analysis Price" in csv_str
        assert "Start of Year Price" in csv_str

        # Write to temporary file and re-import via the core parser
        csv_path = tmp_path / "exported_watchlist.csv"
        csv_path.write_text(csv_str, encoding="utf-8")

        instruments, errors, unresolved, warnings = import_spreadsheet(str(csv_path), "exported_watchlist.csv")
        assert errors == [], f"Import errors encountered: {errors}"
        assert len(instruments) == 1

        imported = instruments[0]
        assert imported.user_ticker == "RMS.PA"
        assert imported.company_name == "Hermes International"
        assert imported.currency == "EUR"
        assert imported.target_price == Decimal("2400.00")
        assert imported.analysis_reference_price == Decimal("2000.00")
        assert imported.analysis_date == date(2024, 3, 15)
        assert imported.start_of_year_price == Decimal("1950.50")
        assert imported.start_of_year_date == date(2026, 1, 2)
        assert imported.comment == "Sector lujo líder con altos márgenes"
        assert imported.active is True

    def test_round_trip_excel_export_import(self, isolated_env, tmp_path):
        """CRITICAL: Test that exported Excel (.xlsx) can be imported with 100% field preservation."""
        inst = Instrument(
            user_ticker="VIS.MC",
            company_name="Viscofan SA",
            exchange=Exchange.SPAIN,
            currency="EUR",
            target_price=Decimal("68.50"),
            analysis_reference_price=Decimal("55.00"),
            analysis_date=date(2024, 6, 20),
            start_of_year_price=Decimal("52.20"),
            start_of_year_date=date(2026, 1, 2),
            comment="Fabricante de envolturas celulósicas",
            active=True,
        )
        upsert_instrument(inst)

        excel_bytes = export_to_excel()
        assert len(excel_bytes) > 0

        # Save to temporary .xlsx file and re-import
        xlsx_path = tmp_path / "exported_watchlist.xlsx"
        xlsx_path.write_bytes(excel_bytes)

        instruments, errors, unresolved, warnings = import_spreadsheet(str(xlsx_path), "exported_watchlist.xlsx")
        assert errors == [], f"Import errors encountered: {errors}"
        assert len(instruments) == 1

        imported = instruments[0]
        assert imported.user_ticker == "VIS.MC"
        assert imported.company_name == "Viscofan SA"
        assert imported.currency == "EUR"
        assert imported.target_price == Decimal("68.50")
        assert imported.analysis_reference_price == Decimal("55.00")
        assert imported.analysis_date == date(2024, 6, 20)
        assert imported.start_of_year_price == Decimal("52.20")
        assert imported.start_of_year_date == date(2026, 1, 2)
        assert imported.comment == "Fabricante de envolturas celulósicas"
        assert imported.active is True
