"""Red->Green behavioral tests for Unit 3 security hardening, input bounds, and HTTP contracts."""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select

from backend.api import main
from backend.api.common import validate_auth_configuration
from backend.api.routers import instruments, refresh
from portfoliomaster.backup.exporters import _sanitize_formula
from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db import session as db_session
from portfoliomaster.db.schema import Base, MarketQuote, UserInstrument
from portfoliomaster.ingest.parser import parse_spreadsheet

TEST_SECRET = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
TEST_SUPABASE_URL = "https://project-ref.supabase.co"


def _mint_jwt(
    user_id: uuid.UUID,
    *,
    role: str | None = "authenticated",
    include_role: bool = True,
    iss: str | None = f"{TEST_SUPABASE_URL}/auth/v1",
    include_iss: bool = True,
) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    if include_role:
        payload["role"] = role
    if include_iss and iss is not None:
        payload["iss"] = iss
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


@pytest.fixture
def isolated_mt_env(monkeypatch, tmp_path):
    """Provide an isolated SQLite-backed multi-tenant FastAPI TestClient environment."""
    db_path = tmp_path / "u3_mt.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("SUPABASE_URL", TEST_SUPABASE_URL)
    monkeypatch.setattr(db_session, "_ENGINE", engine)
    monkeypatch.setattr(db_session, "_SESSION_FACTORY", None)
    try:
        yield engine
    finally:
        db_session._ENGINE = None
        db_session._SESSION_FACTORY = None
        engine.dispose()


def test_production_exception_handler_masks_integrity_and_internal_errors(monkeypatch, isolated_mt_env):
    """In production, IntegrityError / unhandled errors must not leak SQL or constraint details."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    user_id = uuid.uuid4()
    token = _mint_jwt(user_id)

    class IntegrityError(Exception):
        pass

    def raise_integrity(*args, **kwargs):
        raise IntegrityError('duplicate key value violates unique constraint "secret_table_col" DETAIL: Key (x)=(secret)')

    monkeypatch.setattr(instruments, "normalize", raise_integrity)
    client = TestClient(main.app, raise_server_exceptions=False, headers={"Authorization": f"Bearer {token}"})
    res = client.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": False})
    assert res.status_code == 500
    body_text = res.text.lower()
    assert "secret_table_col" not in body_text
    assert "duplicate key" not in body_text


def test_jwt_requires_explicit_authenticated_role_and_prod_supabase_url(monkeypatch, isolated_mt_env):
    """JWT without role claim is rejected (403); production without SUPABASE_URL fails closed."""
    user_id = uuid.uuid4()
    no_role_token = _mint_jwt(user_id, include_role=False)
    client = TestClient(main.app, headers={"Authorization": f"Bearer {no_role_token}"})
    res = client.get("/api/instruments")
    assert res.status_code == 403

    import secrets
    prod_secret = secrets.token_urlsafe(32)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", prod_secret)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        validate_auth_configuration()

    valid_token = jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 3600},
        prod_secret,
        algorithm="HS256",
    )
    res_prod = TestClient(main.app, headers={"Authorization": f"Bearer {valid_token}"}).get("/api/instruments")
    assert res_prod.status_code == 500


def test_sanitize_formula_neutralizes_whitespace_and_control_prefixes():
    """Formula sanitization catches leading tabs, CR, LF, and spaces before trigger characters."""
    for payload in ("=1+1", "+cmd", "-1+1", "@SUM(1,2)", "\t=1+1", "\r+1", "  =SUM(A1)", " \t @cmd"):
        sanitized = _sanitize_formula(payload)
        assert sanitized.startswith("'"), f"Expected leading quote for {payload!r}, got {sanitized!r}"


def test_xlsx_parser_enforces_row_limit_before_materializing(tmp_path):
    """XLSX parser aborts early when rows exceed max_rows without materializing full sheet."""
    xlsx_path = tmp_path / "too_many.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(["Ticker", "Name"])
    for idx in range(12):
        ws.append([f"T{idx}", f"Company {idx}"])
    wb.save(xlsx_path)

    df, err = parse_spreadsheet(str(xlsx_path), "too_many.xlsx", max_rows=10)
    assert df is None
    assert err is not None and "10" in err


def test_import_preview_streams_and_rejects_oversized_upload(monkeypatch, isolated_mt_env):
    """POST /api/import/preview aborts with 413 when streamed bytes exceed MAX_UPLOAD_BYTES."""
    from backend.api.routers import import_export

    monkeypatch.setattr(import_export, "MAX_UPLOAD_BYTES", 64)
    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})
    oversized = b"ticker,company_name\n" + (b"AAPL,Apple\n" * 20)
    res = client.post(
        "/api/import/preview",
        files={"file": ("big.csv", oversized, "text/csv")},
    )
    assert res.status_code == 413


def test_restore_rejects_over_500_instruments_and_invalid_decimal_without_500(isolated_mt_env):
    """JSON restore rejects >500 items and malformed decimals cleanly with 400 (never 500)."""
    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})

    too_many = {
        "version": "1.0",
        "instruments": [{"user_ticker": f"T{i}"} for i in range(501)],
    }
    res_501 = client.post(
        "/api/backup/restore",
        files={"file": ("backup.json", json.dumps(too_many).encode("utf-8"), "application/json")},
    )
    assert res_501.status_code == 400

    bad_dec = {
        "version": "1.0",
        "instruments": [{"user_ticker": "AAPL", "target_price": "not-a-decimal"}],
    }
    res_dec = client.post(
        "/api/backup/restore",
        files={"file": ("bad.json", json.dumps(bad_dec).encode("utf-8"), "application/json")},
    )
    assert res_dec.status_code == 400


def test_import_confirm_sqlite_returns_400_when_zero_committed_with_errors(monkeypatch, tmp_path):
    """SQLite import/confirm must not return 200 OK when committed == 0 and errors occurred."""
    from backend.api.routers import import_export

    db_path = tmp_path / "sqlite_confirm.db"
    monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("SUPABASE_URL", TEST_SUPABASE_URL)
    monkeypatch.setattr(import_export, "is_multi_tenant_db", lambda: False)
    monkeypatch.setattr(import_export, "upsert_instrument", lambda _inst: (_ for _ in ()).throw(RuntimeError("boom")))

    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})
    res = client.post(
        "/api/import/confirm",
        json={"instruments": [{"user_ticker": "AAPL"}]},
    )
    assert res.status_code == 400


def test_post_instrument_preserves_valid_quote_isolates_manual_price_and_validates_dates(
    monkeypatch, isolated_mt_env
):
    """POST /api/instruments must not wipe valid MarketQuote on Yahoo failure, isolate manual_price, and reject bad dates."""
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # Seed valid shared MarketQuote for AAPL
    with db_session.session_scope() as session:
        session.add(
            MarketQuote(
                provider_symbol="AAPL",
                currency="USD",
                exchange="US",
                company_name="Apple Inc.",
                price=Decimal("210.00"),
                previous_close=Decimal("208.00"),
                status="FRESH",
                last_valid_fetched_at=datetime(2026, 11, 20, tzinfo=timezone.utc),
            )
        )
        session.commit()

    client_a = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_a)}"})
    client_b = TestClient(main.app, headers={"Authorization": f"Bearer {_mint_jwt(user_b)}"})

    # 1. Invalid date -> 422
    bad_date = client_a.post(
        "/api/instruments",
        json={"user_ticker": "MSFT", "analysis_date": "not-a-date", "fetch_yahoo": False},
    )
    assert bad_date.status_code == 422

    # 2. Tenant A sends manual_price on AAPL -> must NOT poison shared MarketQuote
    res_manual = client_a.post(
        "/api/instruments",
        json={"user_ticker": "AAPL", "fetch_yahoo": False, "manual_price": 999.99},
    )
    assert res_manual.status_code == 201

    # 3. Tenant B fetches failed Yahoo quote on AAPL -> must NOT wipe existing valid price 210.00
    class FailingYahoo:
        def fetch(self, symbols):
            return {symbols[0]: Quote(price=None, status=QuoteStatus.ERROR, error_message="rate limited")}

    monkeypatch.setattr(refresh, "_get_yahoo_adapter", FailingYahoo)
    monkeypatch.setattr(instruments, "_fetch_start_of_year_quote", lambda *_a, **_kw: None)
    monkeypatch.setattr(instruments, "resolve_company_name", lambda *_a, **_kw: "Apple Inc.")

    res_fail = client_b.post("/api/instruments", json={"user_ticker": "AAPL", "fetch_yahoo": True})
    assert res_fail.status_code == 201

    with db_session.session_scope() as session:
        mq = session.get(MarketQuote, "AAPL")
        assert mq is not None
        assert mq.price == Decimal("210.00")
        assert mq.status in ("FRESH", "ERROR")
        assert mq.last_valid_fetched_at is not None


def test_put_instrument_updates_provider_symbol_clears_company_name_and_validates_dates(isolated_mt_env):
    """PUT /api/instruments/{ticker} recomputes provider_symbol, clears company_name, and validates dates."""
    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})

    create_res = client.post(
        "/api/instruments",
        json={"user_ticker": "SAN", "exchange": "SPAIN", "currency": "EUR", "company_name": "Banco Santander", "fetch_yahoo": False},
    )
    assert create_res.status_code == 201

    # Clear company_name and change exchange to US -> provider_symbol must update from SAN.MC to SAN
    put_res = client.put(
        "/api/instruments/SAN",
        json={"exchange": "US", "currency": "USD", "company_name": ""},
    )
    assert put_res.status_code == 200
    inst = put_res.json()["instrument"]
    assert inst["provider_symbol"] == "SAN"
    assert inst["company_name"] in (None, "")

    # Invalid date on PUT -> 422
    bad_put = client.put("/api/instruments/SAN", json={"analysis_date": "2026-99-99"})
    assert bad_put.status_code == 422


def test_check_yahoo_contract_single_name_lookup_and_502_on_failure(monkeypatch, isolated_mt_env):
    """GET /api/instruments/check-yahoo calls resolve_company_name once, includes previous_close & message, and returns 502 on failure."""
    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})

    name_calls = 0

    def fake_resolve(symbol, ticker_obj=None):
        nonlocal name_calls
        name_calls += 1
        return None  # Trigger fallback path without duplicate call

    class FakeFastInfo:
        last_price = 195.25
        previous_close = 192.10
        currency = "USD"

    class FakeTicker:
        fast_info = FakeFastInfo()

    monkeypatch.setattr(instruments, "resolve_company_name", fake_resolve)
    monkeypatch.setattr(instruments, "_create_ticker", lambda _sym: FakeTicker())

    res = client.get("/api/instruments/check-yahoo?ticker=AAPL")
    assert res.status_code == 200
    data = res.json()
    assert name_calls == 1
    assert data["available"] is True
    assert data["price"] == 195.25
    assert data["previous_close"] == 192.10

    # When ticker creation raises external error, return 502
    monkeypatch.setattr(instruments, "_create_ticker", lambda _sym: (_ for _ in ()).throw(RuntimeError("upstream down")))
    err_res = client.get("/api/instruments/check-yahoo?ticker=AAPL")
    assert err_res.status_code == 502


def test_get_instrument_detail_canonical_payload(isolated_mt_env):
    """GET /api/instruments/{ticker} returns canonical {instrument, quote} without duplicated top-level keys."""
    token = _mint_jwt(uuid.uuid4())
    client = TestClient(main.app, headers={"Authorization": f"Bearer {token}"})

    client.post("/api/instruments", json={"user_ticker": "MSFT", "currency": "USD", "fetch_yahoo": False})
    res = client.get("/api/instruments/MSFT")
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"instrument", "quote"}
    assert body["instrument"]["user_ticker"] == "MSFT"
