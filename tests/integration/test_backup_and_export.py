"""Integration tests for SQLite backups, JSON/CSV/Excel exports, and restore parity."""

from __future__ import annotations

import io
import os
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import openpyxl
import pytest

from portfoliomaster.backup.exporters import (
    export_to_csv,
    export_to_excel,
    export_to_json,
    get_export_records,
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
from portfoliomaster.core.calculations import decline_to_target
from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db.connection import get_connection, init_db
from portfoliomaster.db.repository import (
    get_all_instruments,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    upsert_instrument,
    upsert_quote,
    wipe_database,
)
from portfoliomaster.ingest.import_session import import_spreadsheet


class TestSqliteBackupCore:
    def test_create_validate_and_failure_modes(self, test_db_isolation, tmp_path):
        upsert_instrument(Instrument(user_ticker="AAPL", company_name="Apple Inc.", exchange=Exchange.US, currency="USD", target_price=Decimal("200.00")))
        dest_backup = str(tmp_path / "backups" / "manual_backup.db")
        created_path = create_sqlite_backup(target_path=dest_backup)
        assert os.path.exists(created_path) and os.path.getsize(created_path) > 0
        assert validate_sqlite_backup(created_path) == (True, None)

        ok, err = validate_sqlite_backup(str(tmp_path / "nope.db"))
        assert ok is False and "no existe" in err

        empty_file = tmp_path / "empty.db"
        empty_file.write_bytes(b"")
        ok, err = validate_sqlite_backup(str(empty_file))
        assert ok is False and "vacío" in err

        corrupt_file = tmp_path / "corrupt.db"
        corrupt_file.write_bytes(b"THIS_IS_NOT_A_SQLITE_DATABASE_FILE")
        assert validate_sqlite_backup(str(corrupt_file))[0] is False

        no_table_file = tmp_path / "no_table.db"
        conn = sqlite3.connect(str(no_table_file))
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        ok, err = validate_sqlite_backup(str(no_table_file))
        assert ok is False and "instruments" in err

    def test_automatic_rotation_restore_and_path_traversal(self, test_db_isolation):
        upsert_instrument(Instrument(user_ticker="TSLA", company_name="Tesla Inc."))
        for i in range(13):
            create_automatic_safety_backup(reason=f"step_{i}")
        assert len(list_automatic_backups()) <= 10

        backup_path = create_sqlite_backup()
        upsert_instrument(Instrument(user_ticker="AMZN", company_name="Amazon.com Inc."))
        assert len(get_all_instruments()) == 2

        summary = restore_sqlite_backup(backup_path)
        assert summary["status"] == "ok" and summary["restored_instruments"] == 1
        assert [i.user_ticker for i in get_all_instruments()] == ["TSLA"]

        with pytest.raises(ValueError, match="no válido"):
            restore_automatic_backup("../../../etc/passwd.db")
        with pytest.raises(ValueError, match="no válido"):
            restore_automatic_backup("not_a_db.txt")


class TestExportersAndParity:
    def test_export_and_restore_json(self, test_db_isolation):
        upsert_instrument(
            Instrument(
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
        )
        inserted = get_all_instruments()[0]
        upsert_quote(Quote(instrument_id=inserted.id, price=Decimal("4.80"), previous_close=Decimal("4.75"), provider="mock", status=QuoteStatus.FRESH))

        json_str = export_to_json()
        assert '"version": "1.0"' in json_str and '"user_ticker": "SAN"' in json_str

        wipe_database()
        assert len(get_all_instruments()) == 0

        res = restore_from_json(json_str)
        assert res["status"] == "ok" and res["restored_instruments"] == 1
        restored = get_all_instruments()[0]
        assert restored.target_price == Decimal("5.50")
        assert restored.analysis_reference_price == Decimal("4.00")
        assert restored.start_of_year_price == Decimal("4.20")
        assert get_quote_by_instrument_id(restored.id).price == Decimal("4.80")

    def test_round_trip_csv_and_excel_export_import(self, test_db_isolation, tmp_path):
        upsert_instrument(
            Instrument(
                user_ticker="RMS.PA",
                company_name="Hermes International",
                exchange=Exchange.FRANCE,
                currency="EUR",
                target_price=Decimal("2400.00"),
                analysis_reference_price=Decimal("2000.00"),
                analysis_date=date(2024, 3, 15),
                start_of_year_price=Decimal("1950.50"),
                start_of_year_date=date(2026, 1, 2),
                comment="Sector lujo",
                active=True,
            )
        )

        csv_path = tmp_path / "exported.csv"
        csv_path.write_text(export_to_csv(), encoding="utf-8")
        csv_insts, csv_errors, _, _ = import_spreadsheet(str(csv_path), "exported.csv")
        assert csv_errors == [] and len(csv_insts) == 1
        assert csv_insts[0].target_price == Decimal("2400.00") and csv_insts[0].start_of_year_price == Decimal("1950.50")

        xlsx_path = tmp_path / "exported.xlsx"
        xlsx_path.write_bytes(export_to_excel())
        xlsx_insts, xlsx_errors, _, _ = import_spreadsheet(str(xlsx_path), "exported.xlsx")
        assert xlsx_errors == [] and len(xlsx_insts) == 1
        assert xlsx_insts[0].analysis_reference_price == Decimal("2000.00")

    def test_export_decline_to_target_parity_and_restore_edge_cases(self, tmp_path, monkeypatch):
        target_price, latest_price = Decimal("120.00"), Decimal("100.00")
        assert decline_to_target(target_price, latest_price).decline_to_target == Decimal("20.00")

        upsert_instrument(Instrument(user_ticker="WT_PARITY", provider_symbol="WT_PARITY", exchange=Exchange.US, currency="USD", target_price=target_price, active=True))
        persisted = get_instrument_by_ticker("WT_PARITY")
        upsert_quote(Quote(instrument_id=persisted.id, price=latest_price, previous_close=Decimal("99.00"), status=QuoteStatus.FRESH, quote_timestamp=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)))
        record = next(r for r in get_export_records() if r["user_ticker"] == "WT_PARITY")
        assert float(record["decline_to_target"]) == 20.00

        # JSON restore atomicity
        from decimal import InvalidOperation

        with pytest.raises(InvalidOperation):
            restore_from_json({"version": "1.0", "instruments": [{"user_ticker": "BAD", "analysis_reference_price": "NOT_A_DEC"}]}, create_safety_backup=False)
        assert get_instrument_by_ticker("WT_PARITY") is not None

        # Active boolean string parsing & target_db_path isolation
        restore_from_json(
            {"version": "1.0", "instruments": [{"user_ticker": "INACT_STR", "active": "false"}, {"user_ticker": "ACT_STR", "active": "true"}]},
            create_safety_backup=False,
        )
        assert get_instrument_by_ticker("INACT_STR").active is False
        assert get_instrument_by_ticker("ACT_STR").active is True

        default_db = os.environ["PORTFOLIOMASTER_DB_PATH"]
        custom_db = str(tmp_path / "custom_target.db")
        monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", custom_db)
        init_db()
        monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", default_db)
        restore_from_json({"version": "1.0", "instruments": [{"user_ticker": "CUSTOM_STOCK", "currency": "USD"}]}, target_db_path=custom_db, create_safety_backup=False)
        assert get_instrument_by_ticker("CUSTOM_STOCK") is None
        assert get_instrument_by_ticker("CUSTOM_STOCK", db_path=custom_db) is not None


class TestBackupAndExportAPI:
    def test_export_csv_excel_json_and_preview_round_trip(self, sqlite_api_client):
        sqlite_api_client.post("/api/instruments", json={
            "user_ticker": "SAN",
            "company_name": "Banco Santander",
            "currency": "EUR",
            "target_price": 5.20,
            "analysis_reference_price": 4.10,
            "analysis_date": "2025-04-10",
            "start_of_year_price": 4.05,
            "start_of_year_date": "2026-01-02",
            "comment": "Dividendo bancario robusto",
            "fetch_yahoo": False,
        })

        r_csv = sqlite_api_client.get("/api/export/csv")
        assert r_csv.status_code == 200 and "SAN" in r_csv.text
        prev_csv = sqlite_api_client.post("/api/import/preview", files={"file": ("export.csv", io.BytesIO(r_csv.content), "text/csv")}).json()
        assert prev_csv["errors"] == [] and prev_csv["instruments"][0]["target_price"] == 5.20

        r_xlsx = sqlite_api_client.get("/api/export/excel")
        assert r_xlsx.status_code == 200
        wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content))
        assert wb.active.title == "Watchlist"
        prev_xlsx = sqlite_api_client.post(
            "/api/import/preview",
            files={"file": ("export.xlsx", io.BytesIO(r_xlsx.content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        ).json()
        assert prev_xlsx["errors"] == [] and prev_xlsx["instruments"][0]["target_price"] == 5.20

        r_json = sqlite_api_client.get("/api/export/json")
        assert r_json.status_code == 200 and r_json.json()["version"] == "1.0"

    def test_backup_download_restore_sqlite_json_and_local_list(self, sqlite_api_client):
        sqlite_api_client.post("/api/instruments", json={"user_ticker": "AMD", "company_name": "AMD Inc", "currency": "USD", "fetch_yahoo": False})
        r_dl = sqlite_api_client.get("/api/backup/download")
        assert r_dl.status_code == 200 and r_dl.content.startswith(b"SQLite format 3\x00")

        sqlite_api_client.delete("/api/database")
        assert sqlite_api_client.get("/api/instruments").json()["count"] == 0

        r_res = sqlite_api_client.post("/api/backup/restore", files={"file": ("backup.db", io.BytesIO(r_dl.content), "application/x-sqlite3")})
        assert r_res.status_code == 200 and r_res.json()["restored_instruments"] == 1
        assert sqlite_api_client.get("/api/instruments/AMD").status_code == 200

        # JSON restore + corrupt reject
        r_json = sqlite_api_client.post(
            "/api/backup/restore",
            files={"file": ("backup.json", io.BytesIO(b'{"version":"1.0","instruments":[{"user_ticker":"IBM","active":true}]}'), "application/json")},
        )
        assert r_json.status_code == 200 and sqlite_api_client.get("/api/instruments/IBM").status_code == 200
        assert sqlite_api_client.post("/api/backup/restore", files={"file": ("corrupt.db", io.BytesIO(b"BAD"), "application/x-sqlite3")}).status_code == 400

        # Local safety backup created on wipe -> list and restore + traversal reject
        sqlite_api_client.delete("/api/database")
        backups = sqlite_api_client.get("/api/backup/list").json()["backups"]
        assert len(backups) >= 1
        assert sqlite_api_client.post(f"/api/backup/restore/{backups[0]['filename']}").status_code == 200
        assert sqlite_api_client.post("/api/backup/restore/invalid.txt").status_code == 400
        assert sqlite_api_client.post("/api/backup/restore/..%2F..%2Fsecret.db").status_code in (400, 404)
        assert sqlite_api_client.post("/api/backup/restore/nonexistent_9999.db").status_code == 404
