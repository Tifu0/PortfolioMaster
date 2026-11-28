"""Unit tests for MockProvider, YahooAdapter normalization, suffixes, and historical fetches."""

import concurrent.futures
import threading
from datetime import date, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd

from portfoliomaster.core.config import get_yahoo_suffix
from portfoliomaster.core.models import Exchange, Quote, QuoteStatus
from portfoliomaster.ingest.normalizer import normalize
from portfoliomaster.providers.mock_provider import MockProvider
from portfoliomaster.providers.yahoo_adapter import YahooAdapter, get_resilient_session


def test_mock_provider_batch():
    mock_data = {
        "AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH),
        "GOOG": Quote(price=Decimal("2800.00"), status=QuoteStatus.FRESH),
    }
    provider = MockProvider(mock_data=mock_data)

    results = provider.fetch(["AAPL", "GOOG", "UNKNOWN"])
    assert len(results) == 3
    assert results["AAPL"].price == Decimal("150.00")
    assert results["GOOG"].price == Decimal("2800.00")
    assert results["UNKNOWN"].status == QuoteStatus.UNAVAILABLE


def test_mock_provider_partial_failure():
    provider = MockProvider()
    provider.partial_failure_symbols.add("BAD")

    results = provider.fetch(["BAD", "GOOD"])
    assert results["BAD"].status == QuoteStatus.ERROR
    assert results["GOOD"].status == QuoteStatus.UNAVAILABLE


def test_yahoo_adapter_symbol_normalization_and_suffixes():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("EPA:RMS") == "RMS.PA"
    assert adapter._normalize_symbol_for_yahoo("BME:VIS") == "VIS.MC"
    assert adapter._normalize_symbol_for_yahoo("NASDAQ:AAPL") == "AAPL"
    assert adapter._normalize_symbol_for_yahoo("AAPL.US") == "AAPL"
    assert adapter._normalize_symbol_for_yahoo("AAPL") == "AAPL"
    assert adapter._normalize_symbol_for_yahoo("RMS.PA") == "RMS.PA"
    assert adapter._normalize_symbol_for_yahoo("EPA:RMS.PA") == "RMS.PA"
    assert adapter._normalize_symbol_for_yahoo("XYZ:RMS") == "RMS"
    assert adapter._normalize_symbol_for_yahoo("LON:AZN") == "AZN.L"
    assert adapter._normalize_symbol_for_yahoo("LSE:AZN") == "AZN.L"
    assert adapter._normalize_symbol_for_yahoo("SHE:002847") == "002847.SZ"

    ticker, ex = normalize("IPH", currency="AUD")
    assert (ticker, ex) == ("IPH", Exchange.AUSTRALIA)
    assert get_yahoo_suffix("IPH", ex, currency="AUD") == ".AX"

    ticker, ex = normalize("EPA:RMS", currency="EUR")
    assert (ticker, ex) == ("RMS", Exchange.FRANCE)
    assert get_yahoo_suffix("EPA:RMS", ex, currency="EUR") == ".PA"

    ticker, ex = normalize("LON:AZN", currency="GBX")
    assert (ticker, ex) == ("AZN", Exchange.UK)
    assert get_yahoo_suffix("LON:AZN", ex, currency="GBX") == ".L"

    ticker, ex = normalize("AAPL", currency="USD")
    assert (ticker, ex) == ("AAPL", Exchange.US)
    assert get_yahoo_suffix("AAPL", ex, currency="USD") == ""


def test_fetch_historical_quote_fallback_to_fast_info(monkeypatch):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_fast_info = MagicMock()
    mock_fast_info.last_price = 215.75
    mock_fast_info.previous_close = 214.50
    mock_ticker.fast_info = mock_fast_info
    monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

    today = date.today()
    result = YahooAdapter().fetch_historical_quote_and_date("AAPL", today)
    assert result == (215.75, today)


def test_fetch_historical_quote_lookback_to_previous_trading_day(monkeypatch):
    friday_dt = pd.Timestamp("2026-10-16")
    hist_df = pd.DataFrame({"Close": [198.25]}, index=[friday_dt])
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    monkeypatch.setattr("yfinance.Ticker", lambda symbol: mock_ticker)

    sunday = date(2026, 10, 18)
    result = YahooAdapter().fetch_historical_quote_and_date("AAPL", sunday)
    assert result == (198.25, date(2026, 10, 16))


def test_yahoo_adapter_exposes_historical_and_ytd_methods(monkeypatch):
    """YahooAdapter exposes unified historical and YTD lookup methods cleanly."""
    adapter = YahooAdapter()
    mock_ticker = MagicMock()
    hist_df = pd.DataFrame(
        {"Close": [180.5]},
        index=pd.to_datetime(["2026-01-05"]),
    )
    mock_ticker.history.return_value = hist_df
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: mock_ticker)

    assert adapter.fetch_start_of_year_quote("AAPL", 2026) == (180.5, date(2026, 1, 5))
    assert adapter.fetch_historical_quote_and_date("AAPL", date(2026, 1, 6), window_days=10) == (
        180.5,
        date(2026, 1, 5),
    )
    assert adapter.fetch_historical_quote_for_date("AAPL", date(2026, 1, 6)) == 180.5


def test_yahoo_adapter_uses_utc_aware_timestamps(monkeypatch):
    """YahooAdapter.fetch must produce UTC-aware quote_timestamp and fetched_at."""
    adapter = YahooAdapter()
    mock_ticker = MagicMock()
    mock_ticker.fast_info = {"last_price": 150.0, "previous_close": 148.0, "last_update": 1700000000}
    mock_ticker.get_history_metadata.return_value = {
        "regularMarketPrice": 150.0,
        "chartPreviousClose": 148.0,
        "regularMarketTime": 1700000000,
    }
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: mock_ticker)

    q = adapter.fetch(["AAPL"])["AAPL"]
    assert q.fetched_at is not None and q.fetched_at.tzinfo == timezone.utc
    assert q.quote_timestamp is not None and q.quote_timestamp.tzinfo is not None


def test_yahoo_adapter_resilient_session_isolated_per_thread():
    """get_resilient_session() must return distinct thread-local requests.Session instances."""
    barrier = threading.Barrier(2)

    def _get_in_concurrent_thread():
        barrier.wait(timeout=2)
        return get_resilient_session()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_get_in_concurrent_thread)
        f2 = pool.submit(_get_in_concurrent_thread)
        s1 = f1.result()
        s2 = f2.result()
    assert s1 is not s2


def test_yahoo_adapter_extracts_closest_future_earnings_date_and_filters_past(monkeypatch):
    """YahooAdapter extracts the closest future earnings_date >= today and normalizes past/missing to None."""
    from portfoliomaster.providers.yahoo_adapter import clear_earnings_cache

    clear_earnings_cache()
    adapter = YahooAdapter()
    today = date(2026, 11, 28)

    # 1. Mix of past and multiple future dates in calendar dict -> picks closest future
    t_future = MagicMock()
    t_future.fast_info = {"last_price": 210.0, "previous_close": 208.0, "last_update": 1700000000}
    t_future.get_history_metadata.return_value = {"regularMarketPrice": 210.0, "chartPreviousClose": 208.0, "regularMarketTime": 1700000000}
    t_future.calendar = {
        "Earnings Date": [date(2026, 8, 1), pd.Timestamp("2027-04-30"), date(2027, 1, 28)]
    }
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: t_future)
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._utc_today", lambda: today)

    res = adapter.fetch(["AAPL"])
    assert res["AAPL"].price == Decimal("210.0")
    assert res["AAPL"].earnings_date == date(2027, 1, 28)

    # 2. Only past dates -> None
    clear_earnings_cache()
    t_past = MagicMock()
    t_past.fast_info = {"last_price": 50.0, "previous_close": 49.0, "last_update": 1700000000}
    t_past.get_history_metadata.return_value = {"regularMarketPrice": 50.0, "chartPreviousClose": 49.0, "regularMarketTime": 1700000000}
    t_past.calendar = {"Earnings Date": [date(2026, 10, 15), date(2026, 11, 27)]}
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: t_past)

    res_past = adapter.fetch(["PAST"])
    assert res_past["PAST"].price == Decimal("50.0")
    assert res_past["PAST"].earnings_date is None

    # 3. ETF / empty calendar -> None
    clear_earnings_cache()
    t_etf = MagicMock()
    t_etf.fast_info = {"last_price": 500.0, "previous_close": 498.0, "last_update": 1700000000}
    t_etf.get_history_metadata.return_value = {"regularMarketPrice": 500.0, "chartPreviousClose": 498.0, "regularMarketTime": 1700000000}
    t_etf.calendar = {}
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: t_etf)

    res_etf = adapter.fetch(["SPY"])
    assert res_etf["SPY"].price == Decimal("500.0")
    assert res_etf["SPY"].earnings_date is None


def test_yahoo_adapter_isolates_earnings_errors_and_supports_dataframe_fallback(monkeypatch):
    """Earnings lookup failures never degrade quote fetch; get_earnings_dates DataFrame fallback works."""
    from portfoliomaster.providers.yahoo_adapter import clear_earnings_cache

    today = date(2026, 11, 28)
    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._utc_today", lambda: today)

    # 1. Both calendar and get_earnings_dates raise -> quote still succeeds with earnings_date=None
    clear_earnings_cache()

    class BrokenCalendarTicker:
        fast_info = {"last_price": 125.0, "previous_close": 124.0, "last_update": 1700000000}

        @property
        def calendar(self):
            raise RuntimeError("HTTP 401 Invalid Crumb")

        def get_earnings_dates(self, limit=8):
            raise RuntimeError("Scrape timeout")

    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: BrokenCalendarTicker())
    res_err = YahooAdapter().fetch(["MSFT"])
    assert res_err["MSFT"].price == Decimal("125.0")
    assert res_err["MSFT"].status != QuoteStatus.ERROR
    assert res_err["MSFT"].earnings_date is None

    # 2. calendar raises, get_earnings_dates returns DataFrame with NaT + past + future
    clear_earnings_cache()

    class FallbackEarningsTicker:
        fast_info = {"last_price": 300.0, "previous_close": 295.0, "last_update": 1700000000}

        @property
        def calendar(self):
            raise RuntimeError("Crumb blocked")

        def get_earnings_dates(self, limit=8):
            return pd.DataFrame(
                {"EPS Estimate": [1.0, 1.1, 1.2]},
                index=pd.DatetimeIndex([pd.Timestamp("2026-05-01"), pd.Timestamp("2027-02-15"), pd.NaT]),
            )

    monkeypatch.setattr("portfoliomaster.providers.yahoo_adapter._create_ticker", lambda sym: FallbackEarningsTicker())
    res_fb = YahooAdapter().fetch(["NVDA"])
    assert res_fb["NVDA"].price == Decimal("300.0")
    assert res_fb["NVDA"].earnings_date == date(2027, 2, 15)
