"""Integration tests for SQLite & PostgreSQL repository layers and unified PortfolioStore contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from portfoliomaster.core.models import Exchange, Instrument, Quote, QuoteStatus
from portfoliomaster.db import connection as sqlite_conn
from portfoliomaster.db import session as db_session
from portfoliomaster.db.multi_tenant_repository import (
    GlobalMarketQuotesRepository,
    MultiTenantWatchlistRepository,
    PostgresWatchlistStore,
    RefreshRunRepository,
    clear_quote_delta_cache,
)
from portfoliomaster.db.ports import PortfolioStore
from portfoliomaster.db.repository import (
    SqliteWatchlistStore,
    _parse_date,
    _parse_datetime,
    get_all_instruments,
    get_instrument_by_ticker,
    get_quote_by_instrument_id,
    upsert_instrument,
    upsert_quote,
)
from portfoliomaster.db.schema import Base


def test_sqlite_db_init_and_upsert():
    sqlite_conn.init_db()
    inst = Instrument(
        user_ticker="AAPL",
        provider_symbol="AAPL.US",
        exchange=Exchange.US,
        currency="USD",
        company_name="Apple Inc.",
        analysis_date=date(2026, 9, 17),
        analysis_reference_price=Decimal("166.45"),
        start_of_year_date=date(2026, 1, 2),
        start_of_year_price=Decimal("180.25"),
        target_price=Decimal("140"),
    )
    upsert_instrument(inst)
    upsert_instrument(inst)

    conn = sqlite_conn.get_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT user_ticker, provider_symbol, analysis_reference_price, start_of_year_price, start_of_year_date, target_price "
            "FROM instruments WHERE user_ticker='AAPL'"
        ).fetchone()
        count = cursor.execute("SELECT COUNT(*) FROM instruments WHERE user_ticker='AAPL'").fetchone()[0]
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "AAPL"
    assert row[1] == "AAPL.US"
    assert Decimal(str(row[2])) == Decimal("166.45")
    assert Decimal(str(row[3])) == Decimal("180.25")
    assert str(row[4]) == "2026-01-02"
    assert Decimal(str(row[5])) == Decimal("140")
    assert count == 1


def test_sqlite_preserve_last_valid_price_and_inactive_flag():
    inst = Instrument(user_ticker="BBVA", provider_symbol="BBVA.MC", currency="EUR")
    upsert_instrument(inst)
    persisted = get_instrument_by_ticker("BBVA")
    assert persisted is not None

    last_time = datetime(2026, 10, 21, 17, 30, 0)
    upsert_quote(
        Quote(
            instrument_id=persisted.id,
            price=Decimal("9.45"),
            previous_close=Decimal("9.30"),
            quote_timestamp=last_time,
            status=QuoteStatus.FRESH,
            provider="Yahoo",
        )
    )
    upsert_quote(
        Quote(
            instrument_id=persisted.id,
            price=None,
            previous_close=None,
            quote_timestamp=None,
            status=QuoteStatus.ERROR,
            error_message="HTTP 500: Rate limit exceeded",
            provider="Yahoo",
        )
    )

    stored = get_quote_by_instrument_id(persisted.id)
    assert stored.price == Decimal("9.45")
    assert stored.previous_close == Decimal("9.30")
    assert stored.quote_timestamp == last_time
    assert stored.status == QuoteStatus.ERROR
    assert stored.error_message == "HTTP 500: Rate limit exceeded"

    # Active/inactive filtering
    upsert_instrument(Instrument(user_ticker="ACTIVE_CO", active=True))
    upsert_instrument(Instrument(user_ticker="INACTIVE_CO", active=False))
    assert "INACTIVE_CO" not in [i.user_ticker for i in get_all_instruments(include_inactive=False)]
    assert "INACTIVE_CO" in [i.user_ticker for i in get_all_instruments(include_inactive=True)]

    # SQLite _parse_datetime & _parse_date preservation
    dt_str = "2026-10-22 14:15:30"
    parsed_dt = _parse_datetime(dt_str)
    assert isinstance(parsed_dt, datetime) and parsed_dt == datetime(2026, 10, 22, 14, 15, 30)
    assert _parse_date(dt_str) == date(2026, 10, 22)


def test_tenant_isolation_coexistence_and_queries(in_memory_mt_session):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    watchlist_a = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=user_a)
    watchlist_b = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=user_b)

    inst_a = watchlist_a.create_instrument(
        user_ticker="AAPL", provider_symbol="AAPL", currency="USD", target_price=Decimal("250.00"), comment="User A"
    )
    inst_b = watchlist_b.create_instrument(
        user_ticker="AAPL", provider_symbol="AAPL", currency="USD", target_price=Decimal("190.00"), comment="User B"
    )
    in_memory_mt_session.commit()

    assert inst_a.id != inst_b.id
    assert len(watchlist_a.get_instruments()) == 1
    assert watchlist_a.get_instruments()[0].target_price == Decimal("250.00")
    assert watchlist_b.get_instruments()[0].target_price == Decimal("190.00")
    assert watchlist_a.get_instrument_by_ticker("AAPL").comment == "User A"
    assert watchlist_a.delete_instrument("NON_EXISTENT") is False


def test_case_insensitive_ticker_search_and_tristate_patch(in_memory_mt_session):
    user = uuid.uuid4()
    watchlist = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=user)

    watchlist.create_instrument(
        user_ticker="msft",
        provider_symbol="MSFT",
        target_price=Decimal("35.00"),
        comment="Original thesis notes",
        analysis_date=date(2026, 1, 15),
    )
    in_memory_mt_session.commit()

    assert watchlist.get_instrument_by_ticker("MSFT").user_ticker == "msft"
    assert watchlist.get_instrument_by_ticker("MsFt").user_ticker == "msft"

    watchlist.update_instrument(ticker="msft", fields_set={"comment"}, comment="Updated thesis")
    in_memory_mt_session.commit()
    refreshed = watchlist.get_instrument_by_ticker("MSFT")
    assert refreshed.comment == "Updated thesis"
    assert refreshed.target_price == Decimal("35.00")
    assert refreshed.analysis_date == date(2026, 1, 15)

    watchlist.update_instrument(
        ticker="MSFT",
        fields_set={"target_price", "analysis_date"},
        target_price=None,
        analysis_date=None,
    )
    in_memory_mt_session.commit()
    cleared = watchlist.get_instrument_by_ticker("MSFT")
    assert cleared.target_price is None
    assert cleared.analysis_date is None
    assert cleared.comment == "Updated thesis"


def test_shared_market_quotes_decoupling_and_safe_upsert(in_memory_mt_session):
    user_1 = uuid.uuid4()
    user_2 = uuid.uuid4()

    watchlist_1 = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=user_1)
    watchlist_2 = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=user_2)
    quotes_repo = GlobalMarketQuotesRepository(in_memory_mt_session)

    watchlist_1.create_instrument(user_ticker="SAN", provider_symbol="SAN.MC", currency="EUR")
    watchlist_2.create_instrument(user_ticker="SANTANDER", provider_symbol="SAN.MC", currency="EUR")
    in_memory_mt_session.commit()

    assert quotes_repo.get_quote("SAN.MC") is not None

    now = datetime(2026, 10, 22, 13, 0, 0, tzinfo=timezone.utc)
    q1 = quotes_repo.upsert_market_quote_safe(
        provider_symbol="SAN.MC",
        price=Decimal("4.650000"),
        previous_close=Decimal("4.500000"),
        quote_timestamp=now,
        status="FRESH",
        exchange="BME",
        currency="EUR",
        company_name="Banco Santander",
    )
    in_memory_mt_session.commit()

    pos_1 = watchlist_1.get_positions_with_calculations()[0]
    pos_2 = watchlist_2.get_positions_with_calculations()[0]
    assert pos_1["latest_price"] == 4.65
    assert pos_2["latest_price"] == 4.65
    assert pos_1["daily_variation"] == 3.33
    assert pos_2["daily_variation"] == 3.33

    # Provider error preserves prior valid price
    q2 = quotes_repo.upsert_market_quote_safe(
        provider_symbol="SAN.MC",
        price=None,
        status="ERROR",
        error_message="Yahoo HTTP 503 Service Unavailable",
    )
    in_memory_mt_session.commit()
    assert q2.price == Decimal("4.650000")
    assert q2.previous_close == Decimal("4.500000")
    assert q2.last_valid_fetched_at == q1.last_valid_fetched_at
    assert q2.status == "ERROR"
    assert q2.last_attempt_at is not None


def test_bulk_upsert_preserves_valid_prices(in_memory_mt_session):
    clear_quote_delta_cache()
    repo = GlobalMarketQuotesRepository(in_memory_mt_session)
    now = datetime.now(timezone.utc)

    repo.upsert_market_quotes_batch([
        {
            "provider_symbol": "GOOGL",
            "price": Decimal("180.00"),
            "previous_close": Decimal("178.00"),
            "quote_timestamp": now,
            "status": "FRESH",
            "company_name": "Alphabet Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        },
        {
            "provider_symbol": "AMZN",
            "price": Decimal("190.00"),
            "previous_close": Decimal("188.00"),
            "quote_timestamp": now,
            "status": "FRESH",
            "company_name": "Amazon.com Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        },
    ])
    in_memory_mt_session.commit()

    repo.upsert_market_quotes_batch([
        {"provider_symbol": "GOOGL", "price": Decimal("185.00"), "previous_close": Decimal("180.00"), "status": "FRESH"},
        {"provider_symbol": "AMZN", "price": None, "status": "ERROR", "error_message": "Temporary 500 error"},
    ])
    in_memory_mt_session.commit()

    assert repo.get_quote("GOOGL").price == Decimal("185.00")
    q_amzn = repo.get_quote("AMZN")
    assert q_amzn.price == Decimal("190.00")
    assert q_amzn.status == "ERROR"
    assert q_amzn.error_message == "Temporary 500 error"


def test_import_or_restore_user_watchlist_parity(in_memory_mt_session):
    tenant_id = uuid.uuid4()
    watchlist = MultiTenantWatchlistRepository(in_memory_mt_session, user_id=tenant_id)
    quotes_repo = GlobalMarketQuotesRepository(in_memory_mt_session)

    count = watchlist.import_or_restore_user_watchlist(
        [
            {
                "user_ticker": "SAN",
                "provider_symbol": "SAN.MC",
                "exchange": "BME",
                "currency": "EUR",
                "company_name": "Banco Santander",
                "target_price": "5.50",
                "analysis_date": "2026-01-15",
                "analysis_reference_price": "4.20",
                "active": True,
            },
            {
                "user_ticker": "VIS",
                "provider_symbol": "VIS.MC",
                "exchange": "BME",
                "currency": "EUR",
                "comment": "Watch closely",
                "active": "false",
            },
        ],
        replace_all=True,
    )
    in_memory_mt_session.commit()

    assert count == 2
    assert len(watchlist.get_instruments(active_only=False)) == 2
    san = watchlist.get_instrument_by_ticker("SAN")
    assert san.target_price == Decimal("5.50")
    assert san.analysis_date == date(2026, 1, 15)
    assert watchlist.get_instrument_by_ticker("VIS").active is False
    assert quotes_repo.get_quote("SAN.MC") is not None
    assert quotes_repo.get_quote("VIS.MC") is not None


def test_refresh_run_lifecycle_and_cooldown(in_memory_mt_session):
    repo = RefreshRunRepository(in_memory_mt_session)
    user_id = uuid.uuid4()

    can_rf, err = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf is True and err is None

    run = repo.start_run(total_symbols=50, trigger_type="cron", user_id=user_id)
    in_memory_mt_session.commit()
    assert run.status == "RUNNING"
    assert run.progress_percent == Decimal("0.00")

    can_rf_blocked, err_blocked = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf_blocked is False
    assert "already have a refresh in progress" in err_blocked

    updated = repo.update_progress(run_id=run.id, processed=25, successful=23, failed=2, current_symbol="GOOGL")
    in_memory_mt_session.commit()
    assert updated.processed_symbols == 25
    assert updated.progress_percent == Decimal("50.00")

    completed = repo.complete_run(run_id=run.id, status="PARTIAL", diagnostic_summary="48 succeeded, 2 failed")
    in_memory_mt_session.commit()
    assert completed.status == "PARTIAL" and completed.completed_at is not None

    can_rf_cooldown, err_cooldown = repo.can_user_refresh(user_id=user_id, cooldown_seconds=60)
    assert can_rf_cooldown is False
    assert "Please wait" in err_cooldown


@pytest.mark.parametrize("backend_kind", ["sqlite", "postgres"])
def test_unified_portfolio_store_contract_parity(backend_kind, monkeypatch, tmp_path):
    """SqliteWatchlistStore and PostgresWatchlistStore must satisfy PortfolioStore Protocol identically."""
    if backend_kind == "sqlite":
        db_file = str(tmp_path / "contract_sq.db")
        monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
        sqlite_conn.init_db()
        store: PortfolioStore = SqliteWatchlistStore()
    else:
        db_url = f"sqlite:///{tmp_path / 'contract_pg.db'}"
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
        monkeypatch.setattr(db_session, "_ENGINE", engine)
        monkeypatch.setattr(db_session, "_SESSION_FACTORY", None)
        store = PostgresWatchlistStore(user_id=uuid.uuid4())

    assert isinstance(store, PortfolioStore)

    quote = Quote(
        price=Decimal("210.00"),
        previous_close=Decimal("200.00"),
        quote_timestamp=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        provider="Yahoo",
        status=QuoteStatus.FRESH,
    )
    inst_dict, quote_info = store.create_instrument(
        {
            "user_ticker": "AAPL",
            "provider_symbol": "AAPL",
            "exchange": "US",
            "currency": "USD",
            "company_name": "Apple Inc.",
            "analysis_date": date(2026, 1, 2),
            "analysis_reference_price": Decimal("190.00"),
            "start_of_year_date": date(2026, 1, 2),
            "start_of_year_price": Decimal("185.00"),
            "target_price": Decimal("250.00"),
            "comment": "Core",
            "active": True,
        },
        fetched_quote=quote,
        manual_price=None,
    )
    assert inst_dict["user_ticker"] == "AAPL"
    assert quote_info is not None
    assert store.instrument_exists("AAPL") is True
    assert len(store.list_instruments(active_only=True)) == 1

    detail = store.get_instrument_detail("AAPL")
    assert detail is not None and detail[0]["user_ticker"] == "AAPL"

    positions = store.get_positions(active_only=False)
    assert len(positions) == 1 and positions[0]["latest_price"] == 210.0

    metrics_rows = store.get_metrics_rows()
    assert len(metrics_rows) == 1 and metrics_rows[0][0] == "AAPL"

    snapshot = store.get_instrument_snapshot_for_update("AAPL")
    assert snapshot is not None and snapshot["user_ticker"] == "AAPL"

    updated = store.update_instrument("AAPL", {"comment"}, {"comment": "Updated"})
    assert updated["comment"] == "Updated"

    assert store.delete_instrument("AAPL") is True
    assert store.delete_instrument("AAPL") is False
    assert store.instrument_exists("AAPL") is False


@pytest.mark.parametrize("backend_kind", ["sqlite", "postgres"])
def test_earnings_date_persistence_parity_and_null_handling(backend_kind, monkeypatch, tmp_path):
    """Both SQLite and Postgres stores persist earnings_date (date and None) and expose it in get_positions."""
    if backend_kind == "sqlite":
        db_file = str(tmp_path / "earn_sq.db")
        monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", db_file)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", raising=False)
        sqlite_conn.init_db()
        store: PortfolioStore = SqliteWatchlistStore()
    else:
        db_url = f"sqlite:///{tmp_path / 'earn_pg.db'}"
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("PORTFOLIOMASTER_FORCE_MULTI_TENANT", "true")
        monkeypatch.setattr(db_session, "_ENGINE", engine)
        monkeypatch.setattr(db_session, "_SESSION_FACTORY", None)
        store = PostgresWatchlistStore(user_id=uuid.uuid4())

    next_earnings = date(2027, 1, 28)
    store.create_instrument(
        {
            "user_ticker": "AAPL",
            "provider_symbol": "AAPL",
            "exchange": "US",
            "currency": "USD",
            "company_name": "Apple Inc.",
            "active": True,
        },
        fetched_quote=Quote(
            price=Decimal("220.00"),
            previous_close=Decimal("218.00"),
            quote_timestamp=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            provider="Yahoo",
            status=QuoteStatus.FRESH,
            earnings_date=next_earnings,
        ),
        manual_price=None,
    )
    store.create_instrument(
        {
            "user_ticker": "SPY",
            "provider_symbol": "SPY",
            "exchange": "US",
            "currency": "USD",
            "company_name": "SPDR S&P 500 ETF",
            "active": True,
        },
        fetched_quote=Quote(
            price=Decimal("590.00"),
            previous_close=Decimal("588.00"),
            quote_timestamp=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            provider="Yahoo",
            status=QuoteStatus.FRESH,
            earnings_date=None,
        ),
        manual_price=None,
    )

    positions = {p["user_ticker"]: p for p in store.get_positions(active_only=False)}
    assert positions["AAPL"]["earnings_date"] == "2027-01-28"
    assert positions["SPY"]["earnings_date"] is None

    detail_aapl = store.get_instrument_detail("AAPL")
    assert detail_aapl is not None and detail_aapl[1] is not None
    assert detail_aapl[1]["earnings_date"] == "2027-01-28"
