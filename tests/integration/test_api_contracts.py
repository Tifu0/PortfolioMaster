"""Integration tests for Unit 3/5 HTTP API contracts, router boundaries, and OpenAPI parity."""

from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.api.dependencies import get_yahoo_provider
from backend.api.main import app
from backend.api.routers import instruments
from portfoliomaster.core.models import Quote, QuoteStatus
from portfoliomaster.db import session as db_session
from portfoliomaster.db.schema import MarketQuote
from tests.conftest import mint_jwt

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

BASELINE_OPENAPI_PATHS = {
    "/": ["GET", "HEAD"],
    "/api/backup/download": ["GET"],
    "/api/backup/list": ["GET"],
    "/api/backup/restore": ["POST"],
    "/api/backup/restore/{filename}": ["POST"],
    "/api/config": ["GET"],
    "/api/database": ["DELETE"],
    "/api/export/csv": ["GET"],
    "/api/export/excel": ["GET"],
    "/api/export/json": ["GET"],
    "/api/health": ["GET", "HEAD"],
    "/api/healthcheck": ["GET", "HEAD"],
    "/api/import/confirm": ["POST"],
    "/api/import/preview": ["POST"],
    "/api/instruments": ["GET", "POST"],
    "/api/instruments/check-yahoo": ["GET"],
    "/api/instruments/resolve-missing-analysis-prices": ["POST"],
    "/api/instruments/resolve-missing-ytd-prices": ["POST"],
    "/api/instruments/{ticker}": ["DELETE", "GET", "PUT"],
    "/api/instruments/{ticker}/fetch-analysis-price": ["POST"],
    "/api/instruments/{ticker}/fetch-ytd-price": ["POST"],
    "/api/instruments/{ticker}/refresh": ["POST"],
    "/api/metrics": ["GET"],
    "/api/positions": ["GET"],
    "/api/refresh": ["POST"],
    "/api/refresh/stream": ["GET"],
    "/health": ["GET", "HEAD"],
    "/healthcheck": ["GET", "HEAD"],
}


def test_post_instrument_preserves_valid_quote_isolates_manual_price_and_validates_dates(
    monkeypatch, isolated_mt_env
):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

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

    client_a = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(user_a, include_iss=True)}"})
    client_b = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(user_b, include_iss=True)}"})

    bad_date = client_a.post(
        "/api/instruments",
        json={"user_ticker": "MSFT", "analysis_date": "not-a-date", "fetch_yahoo": False},
    )
    assert bad_date.status_code == 422

    res_manual = client_a.post(
        "/api/instruments",
        json={"user_ticker": "AAPL", "fetch_yahoo": False, "manual_price": 999.99},
    )
    assert res_manual.status_code == 201

    class FailingYahoo:
        def fetch(self, symbols):
            return {symbols[0]: Quote(price=None, status=QuoteStatus.ERROR, error_message="rate limited")}

    monkeypatch.setitem(app.dependency_overrides, get_yahoo_provider, FailingYahoo)
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
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    create_res = client.post(
        "/api/instruments",
        json={"user_ticker": "SAN", "exchange": "SPAIN", "currency": "EUR", "company_name": "Banco Santander", "fetch_yahoo": False},
    )
    assert create_res.status_code == 201

    put_res = client.put(
        "/api/instruments/SAN",
        json={"exchange": "US", "currency": "USD", "company_name": ""},
    )
    assert put_res.status_code == 200
    inst = put_res.json()["instrument"]
    assert inst["provider_symbol"] == "SAN"
    assert inst["company_name"] in (None, "")

    assert client.put("/api/instruments/SAN", json={"analysis_date": "2026-99-99"}).status_code == 422


def test_check_yahoo_contract_single_name_lookup_and_502_on_failure(monkeypatch, isolated_mt_env):
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    name_calls = 0

    def fake_resolve(symbol, ticker_obj=None):
        nonlocal name_calls
        name_calls += 1
        return None

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
    assert name_calls == 1 and data["available"] is True and data["price"] == 195.25 and data["previous_close"] == 192.10

    monkeypatch.setattr(instruments, "_create_ticker", lambda _sym: (_ for _ in ()).throw(RuntimeError("upstream down")))
    assert client.get("/api/instruments/check-yahoo?ticker=AAPL").status_code == 502


def test_get_instrument_detail_canonical_payload(isolated_mt_env):
    client = TestClient(app, headers={"Authorization": f"Bearer {mint_jwt(uuid.uuid4(), include_iss=True)}"})
    client.post("/api/instruments", json={"user_ticker": "MSFT", "currency": "USD", "fetch_yahoo": False})
    res = client.get("/api/instruments/MSFT")
    assert res.status_code == 200
    assert set(res.json().keys()) == {"instrument", "quote"}
    assert res.json()["instrument"]["user_ticker"] == "MSFT"


def test_no_sys_modules_backend_api_main_hack_in_src_or_backend():
    """Production code must never inspect sys.modules['backend.api.main']."""
    offenders: list[str] = []
    for folder in (REPO_ROOT / "src", REPO_ROOT / "backend" / "api"):
        for py_file in folder.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            if 'sys.modules["backend.api.main"]' in text or 'sys.modules.get("backend.api.main")' in text:
                offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert offenders == [], f"Found dynamic sys.modules backend.api.main lookup in: {offenders}"


def test_routers_have_zero_is_multi_tenant_db_branches():
    """Thin routers under backend/api/routers/ must not branch on is_multi_tenant_db()."""
    routers_dir = REPO_ROOT / "backend" / "api" / "routers"
    offenders = [p.name for p in routers_dir.glob("*.py") if "is_multi_tenant_db(" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"Routers still contain is_multi_tenant_db() branches: {offenders}"


def test_router_monoliths_are_slimmed_and_openapi_intact():
    """instruments.py and refresh.py stay within line budgets and OpenAPI schema keeps 100% parity."""
    instruments_lines = len((REPO_ROOT / "backend" / "api" / "routers" / "instruments.py").read_text(encoding="utf-8").splitlines())
    refresh_lines = len((REPO_ROOT / "backend" / "api" / "routers" / "refresh.py").read_text(encoding="utf-8").splitlines())
    assert instruments_lines <= 320, f"instruments.py is {instruments_lines} lines"
    assert refresh_lines <= 220, f"refresh.py is {refresh_lines} lines"

    spec = app.openapi()
    actual_routes = {
        path: sorted(m.upper() for m in methods if m.lower() in ("get", "post", "put", "patch", "delete", "head", "options"))
        for path, methods in spec.get("paths", {}).items()
    }
    assert actual_routes == BASELINE_OPENAPI_PATHS
