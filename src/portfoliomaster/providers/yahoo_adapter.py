from collections import OrderedDict
import inspect
import concurrent.futures
import logging
import math
import threading
import time
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
import os
import tempfile
from typing import Dict, Iterable, List, Optional, Any
import warnings
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Silence known upstream Pandas / yfinance deprecation warnings (e.g. Pandas4Warning inplace keyword)
try:
    for _w in dir(pd.errors):
        if "Warning" in _w:
            warnings.simplefilter("ignore", getattr(pd.errors, _w))
except Exception:
    pass
warnings.filterwarnings("ignore", message=".*inplace.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="yfinance")

import yfinance as yf

# Configure resilient TzCache location to prevent race condition [Errno 17] across threads
try:
    _tz_dir = os.path.join(tempfile.gettempdir(), "py-yfinance")
    os.makedirs(_tz_dir, exist_ok=True)
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(_tz_dir)
except Exception:
    pass

# Upstream yfinance bug fix & cloud speed accelerator:
# 1. Prevent storing rate limit messages (e.g. 'Too Many Requests') as valid crumbs.
# 2. Cooldown cache for rate-limited crumbs to prevent 3.5s blocking per ticker on cloud IPs (Render).
# 3. Yahoo's Chart API (/v8/finance/chart) works 100% without a crumb, so when rate-limited (or on Render),
#    we bypass crumb fetch instantly (0.0s instead of 3.5s per ticker).
try:
    import time
    import yfinance.data as _yd

    _CRUMB_LOCK = threading.Lock()
    _CRUMB_RATE_LIMITED_UNTIL = time.time() + 86400.0 if os.environ.get("RENDER") else 0.0
    _orig_get_cookie_and_crumb = _yd.YfData._get_cookie_and_crumb

    def _sanitize_crumb_val(val: Any) -> Optional[str]:
        if val is None:
            return None
        s = str(val)
        if "Too Many Requests" in s or "<html>" in s or len(s) > 50 or "\n" in s:
            return None
        return val

    def _resilient_get_cookie_and_crumb(self, timeout=30):
        global _CRUMB_RATE_LIMITED_UNTIL
        now = time.time()
        with _CRUMB_LOCK:
            rate_limited_until = _CRUMB_RATE_LIMITED_UNTIL
        if now < rate_limited_until:
            return None, self._cookie_strategy

        crumb_timeout = min(timeout, 2)
        try:
            crumb, strategy = _orig_get_cookie_and_crumb(self, timeout=crumb_timeout)
            if crumb is not None and not _sanitize_crumb_val(crumb):
                self._crumb = None
                with _CRUMB_LOCK:
                    _CRUMB_RATE_LIMITED_UNTIL = time.time() + 900.0
                return None, strategy
            return crumb, strategy
        except _yd.YFRateLimitError:
            self._crumb = None
            with _CRUMB_LOCK:
                _CRUMB_RATE_LIMITED_UNTIL = time.time() + 900.0
            return None, self._cookie_strategy
        except Exception as e:
            self._crumb = None
            if "429" in str(e) or "Too Many Requests" in str(e) or "timeout" in str(e).lower():
                with _CRUMB_LOCK:
                    _CRUMB_RATE_LIMITED_UNTIL = time.time() + 900.0
                return None, self._cookie_strategy
            raise

    _yd.YfData._get_cookie_and_crumb = _resilient_get_cookie_and_crumb
except Exception:
    pass

from .base import MarketDataProvider
from ..core.models import Quote, QuoteStatus, FreshnessConfig, Exchange
from ..core.parsing import parse_date, parse_decimal
from ..core.config import (
    FRESHNESS_PER_EXCHANGE,
    YAHOO_SUFFIXES,
    EXCHANGE_HINTS,
    PREFIX_TO_YAHOO_SUFFIX,
)

_THREAD_LOCAL = threading.local()

MAX_EARNINGS_CACHE_ENTRIES = 2048
EARNINGS_CACHE_TTL_SECONDS = float(os.environ.get("EARNINGS_CACHE_TTL_SECONDS", str(6 * 3600)))
_EARNINGS_CACHE: OrderedDict[str, tuple[Optional[date], float]] = OrderedDict()
_EARNINGS_CACHE_LOCK = threading.Lock()


def _utc_today() -> date:
    """Return current UTC calendar date (isolated helper for deterministic tests)."""
    return datetime.now(timezone.utc).date()


def clear_earnings_cache(symbols: Optional[Iterable[str]] = None) -> None:
    """Clear the bounded in-memory earnings_date cache globally or for specific symbols."""
    with _EARNINGS_CACHE_LOCK:
        if symbols is None:
            _EARNINGS_CACHE.clear()
        else:
            for sym in symbols:
                key = str(sym).strip().upper()
                if key:
                    _EARNINGS_CACHE.pop(key, None)


def _get_cached_earnings_date(symbol: str, now_monotonic: Optional[float] = None) -> tuple[bool, Optional[date]]:
    """Lookup cached earnings_date if present and within TTL."""
    if EARNINGS_CACHE_TTL_SECONDS <= 0:
        return False, None
    key = symbol.strip().upper()
    now_ts = time.monotonic() if now_monotonic is None else now_monotonic
    with _EARNINGS_CACHE_LOCK:
        entry = _EARNINGS_CACHE.get(key)
        if entry is None:
            return False, None
        val, cached_at = entry
        if now_ts - cached_at >= EARNINGS_CACHE_TTL_SECONDS:
            _EARNINGS_CACHE.pop(key, None)
            return False, None
        _EARNINGS_CACHE.move_to_end(key)
        return True, val


def _set_cached_earnings_date(symbol: str, value: Optional[date], now_monotonic: Optional[float] = None) -> None:
    """Store earnings_date in bounded LRU+TTL cache."""
    if EARNINGS_CACHE_TTL_SECONDS <= 0:
        return
    key = symbol.strip().upper()
    if not key:
        return
    now_ts = time.monotonic() if now_monotonic is None else now_monotonic
    with _EARNINGS_CACHE_LOCK:
        _EARNINGS_CACHE[key] = (value, now_ts)
        _EARNINGS_CACHE.move_to_end(key)
        while len(_EARNINGS_CACHE) > MAX_EARNINGS_CACHE_ENTRIES:
            _EARNINGS_CACHE.popitem(last=False)


def _coerce_to_date(value: Any) -> Optional[date]:
    """Coerce Timestamp, datetime, date, epoch seconds, or date string into date."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        try:
            return value.date()
        except Exception:
            return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (ValueError, OSError, OverflowError):
            return None
    return parse_date(value)


def normalize_next_earnings_date(raw_values: Any, *, today: Optional[date] = None) -> Optional[date]:
    """Extract the closest upcoming earnings date (>= today) from heterogeneous values."""
    if raw_values is None:
        return None

    ref_today = today or _utc_today()
    items: list[Any]
    if isinstance(raw_values, (list, tuple, set, pd.Series, pd.Index)):
        items = list(raw_values)
    else:
        items = [raw_values]

    future_dates: list[date] = []
    for item in items:
        parsed = _coerce_to_date(item)
        if parsed is not None and parsed >= ref_today:
            future_dates.append(parsed)

    return min(future_dates) if future_dates else None


def _extract_next_earnings_date(ticker: Any, *, today: Optional[date] = None) -> Optional[date]:
    """Safely extract upcoming earnings_date from yfinance Ticker without failing quote fetch."""
    ref_today = today or _utc_today()
    calendar_failed = False

    try:
        cal = getattr(ticker, "calendar", None)
        if isinstance(cal, dict):
            for key in ("Earnings Date", "earningsDate", "earnings_date"):
                if key in cal:
                    return normalize_next_earnings_date(cal.get(key), today=ref_today)
            return None
        if isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.columns:
                return normalize_next_earnings_date(cal["Earnings Date"], today=ref_today)
            if "Earnings Date" in cal.index:
                return normalize_next_earnings_date(cal.loc["Earnings Date"], today=ref_today)
            return None
    except Exception:
        calendar_failed = True

    if calendar_failed:
        try:
            get_ed = getattr(ticker, "get_earnings_dates", None)
            if callable(get_ed):
                df = get_ed(limit=8)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    if "Earnings Date" in df.columns:
                        return normalize_next_earnings_date(df["Earnings Date"], today=ref_today)
                    return normalize_next_earnings_date(df.index, today=ref_today)
        except Exception:
            pass

    return None


def get_resilient_session() -> requests.Session:
    """Thread-local requests session with retry strategy and browser user agent for Yahoo Finance."""
    session = getattr(_THREAD_LOCAL, "resilient_session", None)
    if session is None:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        _THREAD_LOCAL.resilient_session = session
    return session


def _create_ticker(symbol: str, session: Optional[requests.Session] = None) -> yf.Ticker:
    """Create yf.Ticker instance with resilient session if supported by callable signature."""
    ticker = None
    try:
        sig = inspect.signature(yf.Ticker)
        if "session" in sig.parameters:
            ticker = yf.Ticker(symbol, session=session or get_resilient_session())
    except Exception:
        pass
    if ticker is None:
        ticker = yf.Ticker(symbol)

    # Neutralize _quote._info to prevent yfinance fallback from calling quoteSummary
    # which triggers HTTP 401 Unauthorized / Invalid Crumb on cloud IPs (Render)
    try:
        if hasattr(ticker, "_quote") and hasattr(ticker._quote, "_info"):
            ticker._quote._info = {}
    except Exception:
        pass

    return ticker


def _fi_get(fi, *keys) -> Optional[Any]:
    """Prueba varias claves/alias en fast_info. Devuelve el primer valor no nulo."""
    for key in keys:
        try:
            val = getattr(fi, key)
            if val is not None:
                return val
        except Exception:
            pass
        try:
            val = fi[key]
            if val is not None:
                return val
        except Exception:
            pass
    return None


def resolve_company_name(symbol: str, ticker_obj: Optional[yf.Ticker] = None) -> Optional[str]:
    """Resolve human-readable company name for a ticker without triggering 401 crumb errors."""
    if not symbol or not str(symbol).strip():
        return None
    sym = str(symbol).strip()

    # 1. Chart metadata via fast_info (ultra fast, provides shortName/longName, no crumb needed)
    try:
        t = ticker_obj or _create_ticker(sym)
        fi = getattr(t, "fast_info", None)
        if fi:
            md_fn = getattr(fi, "_get_exchange_metadata", None)
            if callable(md_fn):
                meta = md_fn()
                if isinstance(meta, dict):
                    name = meta.get("longName") or meta.get("shortName")
                    if name and str(name).strip():
                        return str(name).strip()
    except Exception:
        pass

    # 2. Yahoo Finance Search API (returns clean name without crumb or rate limit)
    try:
        search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={sym}&quotesCount=1"
        s = get_resilient_session()
        resp = s.get(search_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            quotes = data.get("quotes", [])
            if quotes and isinstance(quotes, list):
                q = quotes[0]
                name = q.get("longname") or q.get("shortname")
                if name and str(name).strip():
                    return str(name).strip()
    except Exception:
        pass

    return None


class YahooAdapter(MarketDataProvider):
    """Yahoo Finance adapter for MarketDataProvider."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------ #
    # Helpers de sufijos
    # ------------------------------------------------------------------ #
    def _suffix_for_prefix(self, prefix: str) -> Optional[str]:
        """
        Devuelve el sufijo Yahoo para un prefijo de exchange.
        Prioriza PREFIX_TO_YAHOO_SUFFIX (más específico, ej. SHE -> .SZ vs SSE -> .SS);
        si falla, usa EXCHANGE_HINTS + YAHOO_SUFFIXES.
        Devuelve None si no se puede determinar (no forzamos sufijo).
        """
        prefix = prefix.strip().upper()

        # 1) Prefijo específico directo (ej. SHE -> .SZ, SSE -> .SS, EPA -> .PA)
        if prefix in PREFIX_TO_YAHOO_SUFFIX:
            return PREFIX_TO_YAHOO_SUFFIX[prefix]

        # 2) Vía configuración oficial
        exchange = EXCHANGE_HINTS.get(prefix)
        if exchange is not None and exchange in YAHOO_SUFFIXES:
            return YAHOO_SUFFIXES[exchange]

        return None

    def _get_exchange_from_symbol(self, symbol: str) -> Exchange:
        symbol = symbol.strip().upper()

        # 1) Sufijo Yahoo -> exchange
        for exchange, suffix in YAHOO_SUFFIXES.items():
            if suffix and symbol.endswith(suffix):
                return exchange

        # 2) Prefijo -> exchange
        if ":" in symbol:
            prefix, _ = symbol.split(":", 1)
            prefix = prefix.upper()
            exchange = EXCHANGE_HINTS.get(prefix)
            if exchange is not None:
                return exchange
            # Fallback: si sabemos el sufijo, intentamos deducir el exchange
            suffix = PREFIX_TO_YAHOO_SUFFIX.get(prefix)
            if suffix:
                for ex, suf in YAHOO_SUFFIXES.items():
                    if suf == suffix:
                        return ex
            # Prefijos US-like sin sufijo
            if prefix in {"US", "NASDAQ", "NYSE", "AMEX", "NYSEARCA"}:
                return Exchange.US

        return Exchange.US

    def _to_decimal(self, value) -> Optional[Decimal]:
        return parse_decimal(value)

    def resolve_company_name(self, symbol: str, ticker: Optional[yf.Ticker] = None) -> Optional[str]:
        """Resolve display company name for a Yahoo symbol."""
        return resolve_company_name(symbol, ticker)

    def fetch_next_earnings_date(self, symbol: str) -> Optional[date]:
        """Fetch next upcoming earnings date (>= UTC today) for a symbol with TTL cache."""
        if not symbol or not str(symbol).strip():
            return None
        y_sym = self._normalize_symbol_for_yahoo(symbol)
        hit, cached = _get_cached_earnings_date(y_sym)
        if hit:
            return cached
        try:
            t = _create_ticker(y_sym)
            resolved = _extract_next_earnings_date(t)
        except Exception as ex:
            self.logger.debug("Error fetching earnings date for %s: %s", y_sym, ex)
            resolved = None
        _set_cached_earnings_date(y_sym, resolved)
        return resolved

    def fetch_start_of_year_quote(
        self, provider_symbol: str, year: Optional[int] = None
    ) -> Optional[tuple[float, date]]:
        """Fetch closing price and trading date for the beginning of the given (or current) year."""
        y = year or date.today().year
        target_date = date(y, 1, 1)
        if not provider_symbol:
            return None
        try:
            t = _create_ticker(provider_symbol)
            start_str = target_date.isoformat()
            end_str = (target_date + timedelta(days=10)).isoformat()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hist = t.history(start=start_str, end=end_str)
                if hist.empty or "Close" not in hist:
                    hist = t.history(period="ytd")
            if not hist.empty and "Close" in hist:
                close_series = hist["Close"].dropna()
                if not close_series.empty:
                    price = close_series.iloc[0]
                    idx = close_series.index[0]
                    actual_dt = (
                        idx.date()
                        if hasattr(idx, "date")
                        else (
                            idx.to_pydatetime().date()
                            if hasattr(idx, "to_pydatetime")
                            else target_date
                        )
                    )
                    if float(price) > 0:
                        return round(float(price), 4), actual_dt
        except Exception:
            pass
        return None

    def fetch_historical_quote_and_date(
        self, provider_symbol: str, target_date: date, window_days: int = 10
    ) -> Optional[tuple[float, date]]:
        """Fetch closing price and trading date on or before target_date with resilient lookback.

        Only falls back to fast_info when target_date is today or within the last 5 days.
        """
        if not provider_symbol or not target_date:
            return None
        try:
            if target_date.month == 1 and target_date.day == 1:
                return self.fetch_start_of_year_quote(provider_symbol, target_date.year)

            t = _create_ticker(provider_symbol)
            start_str = (target_date - timedelta(days=window_days)).isoformat()
            end_str = (target_date + timedelta(days=1)).isoformat()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hist = t.history(start=start_str, end=end_str)

            if not hist.empty and "Close" in hist:
                valid_rows = []
                for idx, val in hist["Close"].dropna().items():
                    row_dt = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
                    if row_dt <= target_date and float(val) > 0:
                        valid_rows.append((float(val), row_dt))
                if valid_rows:
                    price, actual_dt = valid_rows[-1]
                    return round(price, 4), actual_dt

            days_from_today = (date.today() - target_date).days
            if 0 <= days_from_today <= 5:
                price = None
                actual_dt = target_date
                try:
                    fi = getattr(t, "fast_info", None)
                    if fi:
                        lp = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
                        if lp is not None and not math.isnan(float(lp)) and float(lp) > 0:
                            price = float(lp)
                        if price is None:
                            pc = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
                            if pc is not None and not math.isnan(float(pc)) and float(pc) > 0:
                                price = float(pc)
                except Exception:
                    pass

                if price is None:
                    try:
                        hist_recent = t.history(period="5d")
                        if not hist_recent.empty and "Close" in hist_recent:
                            recent_series = hist_recent["Close"].dropna()
                            if not recent_series.empty:
                                last_val = recent_series.iloc[-1]
                                if float(last_val) > 0:
                                    price = float(last_val)
                                    last_idx = recent_series.index[-1]
                                    actual_dt = last_idx.date() if hasattr(last_idx, "date") else target_date
                    except Exception:
                        pass

                if price is not None and price > 0:
                    return round(price, 4), actual_dt
        except Exception as e:
            self.logger.debug("Error in fetch_historical_quote_and_date for %s: %s", provider_symbol, e)
        return None

    def fetch_historical_quote_for_date(
        self, provider_symbol: str, target_date: date
    ) -> Optional[float]:
        """Fetch closing price on or shortly before target_date from Yahoo Finance."""
        res = self.fetch_historical_quote_and_date(provider_symbol, target_date, window_days=10)
        return res[0] if res else None

    def _normalize_symbol_for_yahoo(self, symbol: str) -> str:
        """
        Convierte el símbolo interno al formato de Yahoo Finance.

        Reglas:
          - 'EPA:RMS'      -> 'RMS.PA'
          - 'BME:VIS'      -> 'VIS.MC'
          - 'NASDAQ:AAPL'  -> 'AAPL'      (US no lleva sufijo)
          - 'AAPL'         -> 'AAPL'
          - 'AAPL.US'      -> 'AAPL'
          - 'RMS.PA'       -> 'RMS.PA'    (ya tiene sufijo)
        """
        symbol = symbol.strip().upper()

        # Caso con prefijo de exchange
        if ":" in symbol:
            prefix, ticker = symbol.split(":", 1)
            prefix = prefix.strip().upper()
            ticker = ticker.strip().upper()

            # ¿El ticker ya viene con sufijo Yahoo? Entonces respétalo.
            for suffix in YAHOO_SUFFIXES.values():
                if suffix and ticker.endswith(suffix):
                    return ticker
            # También respeta sufijos del fallback
            for suffix in PREFIX_TO_YAHOO_SUFFIX.values():
                if suffix and ticker.endswith(suffix):
                    return ticker

            suffix = self._suffix_for_prefix(prefix)

            # Prefijo desconocido: devolvemos el ticker sin prefijo
            # (mejor que devolver "EPA:RMS" que Yahoo no entiende)
            if suffix is None:
                self.logger.warning(
                    f"Prefijo de exchange desconocido '{prefix}' en '{symbol}'. "
                    f"Se usará '{ticker}' sin sufijo."
                )
                return ticker

            # US o sufijo vacío -> ticker pelado
            if suffix == "":
                return ticker

            return f"{ticker}{suffix}"

        # Sin prefijo
        if symbol.endswith(".US"):
            return symbol[:-3]
        return symbol

    # ------------------------------------------------------------------ #
    # Extracción de datos
    # ------------------------------------------------------------------ #
    def _extract_quote_data(self, ticker) -> Dict[str, Any]:
        """Saca precio, prev_close y timestamp con múltiples fallbacks."""
        price = None
        previous_close = None
        quote_timestamp = None

        try:
            fi = ticker.fast_info

            # Fast path 1: Chart metadata (no crumb or cookies needed, immune to HTTP 429/401)
            md_fn = getattr(fi, "_get_exchange_metadata", None)
            if callable(md_fn):
                try:
                    meta = md_fn()
                    if isinstance(meta, dict):
                        price = meta.get("regularMarketPrice") or meta.get("fulldayPrice")
                        previous_close = meta.get("chartPreviousClose")
                        rm_time = meta.get("regularMarketTime")
                        if rm_time:
                            if isinstance(rm_time, datetime):
                                quote_timestamp = (
                                    rm_time if rm_time.tzinfo else rm_time.replace(tzinfo=timezone.utc)
                                )
                            elif isinstance(rm_time, (int, float)):
                                quote_timestamp = datetime.fromtimestamp(rm_time, tz=timezone.utc)
                except Exception as meta_err:
                    self.logger.debug(f"Metadata extract failed: {meta_err}")

            if price is None:
                price = _fi_get(fi, "last_price", "lastPrice", "regularMarketPrice")
            if previous_close is None:
                previous_close = _fi_get(
                    fi, "previous_close", "previousClose", "regularMarketPreviousClose"
                )
            if quote_timestamp is None:
                qt = _fi_get(fi, "last_update", "lastUpdate")
                if qt is not None:
                    if hasattr(qt, "to_pydatetime"):
                        py_dt = qt.to_pydatetime()
                        quote_timestamp = py_dt if py_dt.tzinfo else py_dt.replace(tzinfo=timezone.utc)
                    elif isinstance(qt, (int, float)):
                        quote_timestamp = datetime.fromtimestamp(qt, tz=timezone.utc)
                    elif isinstance(qt, datetime):
                        quote_timestamp = qt if qt.tzinfo else qt.replace(tzinfo=timezone.utc)
        except Exception as e:
            self.logger.debug(f"fast_info falló: {e}")

        # Fallback con history() si no tenemos precio
        if price is None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    hist = ticker.history(period="5d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    if quote_timestamp is None:
                        idx = hist.index[-1]
                        quote_timestamp = (
                            idx.to_pydatetime()
                            if hasattr(idx, "to_pydatetime")
                            else None
                        )
                    if previous_close is None:
                        if len(hist) >= 2:
                            previous_close = hist["Close"].iloc[-2]
                        else:
                            previous_close = hist["Open"].iloc[0]
            except Exception as e:
                self.logger.debug(f"history falló: {e}")

        return {
            "price": self._to_decimal(price),
            "previous_close": self._to_decimal(previous_close),
            "quote_timestamp": quote_timestamp,
        }

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def fetch(self, symbols: List[str]) -> Dict[str, Quote]:
        results: Dict[str, Quote] = {}
        if not symbols:
            return results

        # Normalize symbols to Yahoo format
        symbol_map: Dict[str, str] = {
            s: self._normalize_symbol_for_yahoo(s) for s in symbols
        }
        unique_yahoo_symbols = list(set(symbol_map.values()))

        batch_quotes_data: Dict[str, Dict[str, Any]] = {}

        # Vectorized multi-threaded batch download when 2 or more symbols are requested
        if len(unique_yahoo_symbols) > 1:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    df = yf.download(
                        unique_yahoo_symbols,
                        period="5d",
                        group_by="ticker",
                        threads=True,
                        progress=False,
                        session=get_resilient_session(),
                    )
                if df is not None and not df.empty and isinstance(df.columns, pd.MultiIndex):
                    for y_sym in unique_yahoo_symbols:
                        try:
                            if y_sym in df.columns.get_level_values(0):
                                sub = df[y_sym]
                                if "Close" in sub:
                                    close_s = sub["Close"].dropna()
                                    if not close_s.empty:
                                        last_p = close_s.iloc[-1]
                                        if pd.notna(last_p) and float(last_p) > 0:
                                            prev_p = (
                                                close_s.iloc[-2]
                                                if len(close_s) >= 2
                                                else (
                                                    sub["Open"].dropna().iloc[-1]
                                                    if "Open" in sub
                                                    and not sub["Open"].dropna().empty
                                                    else None
                                                )
                                            )
                                            last_idx = close_s.index[-1]
                                            ts = (
                                                last_idx.to_pydatetime()
                                                if hasattr(last_idx, "to_pydatetime")
                                                else None
                                            )
                                            batch_quotes_data[y_sym] = {
                                                "price": self._to_decimal(last_p),
                                                "previous_close": self._to_decimal(prev_p),
                                                "quote_timestamp": ts,
                                            }
                        except Exception as parse_err:
                            self.logger.debug(
                                f"Error parsing batch quote for {y_sym}: {parse_err}"
                            )
            except Exception as dl_err:
                self.logger.warning(
                    f"Vectorized yf.download failed, falling back to individual fetching: {dl_err}"
                )

        # High-performance parallel fallback for missing or unparsed symbols (e.g. international tickers)
        missing_symbols = [
            s for s in unique_yahoo_symbols
            if not batch_quotes_data.get(s) or batch_quotes_data[s].get("price") is None
        ]
        created_tickers: Dict[str, Any] = {}

        if missing_symbols:
            def _fetch_one_symbol(y_sym: str) -> tuple[str, Dict[str, Any], Optional[Any]]:
                try:
                    t = _create_ticker(y_sym)
                    return y_sym, self._extract_quote_data(t), t
                except Exception as ex:
                    self.logger.debug(f"Error fetching quote for {y_sym}: {ex}")
                    return y_sym, {"price": None, "previous_close": None, "quote_timestamp": None}, None

            max_workers = min(12, len(missing_symbols))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                for y_sym, data, ticker_obj in executor.map(_fetch_one_symbol, missing_symbols):
                    if ticker_obj is not None:
                        created_tickers[y_sym] = ticker_obj
                    if data and data.get("price") is not None:
                        batch_quotes_data[y_sym] = data

        # Resolve upcoming earnings_date in bounded parallel with TTL cache (errors isolated)
        earnings_map: Dict[str, Optional[date]] = {}
        earnings_targets = [
            y_sym for y_sym in unique_yahoo_symbols
            if batch_quotes_data.get(y_sym) and batch_quotes_data[y_sym].get("price") is not None
        ]
        uncached_earnings: List[str] = []
        for y_sym in earnings_targets:
            hit, cached_dt = _get_cached_earnings_date(y_sym)
            if hit:
                earnings_map[y_sym] = cached_dt
            else:
                uncached_earnings.append(y_sym)

        if uncached_earnings:
            def _fetch_earnings_one(y_sym: str) -> tuple[str, Optional[date]]:
                try:
                    t = created_tickers.get(y_sym) or _create_ticker(y_sym)
                    return y_sym, _extract_next_earnings_date(t)
                except Exception as ex:
                    self.logger.debug("Error fetching earnings date for %s: %s", y_sym, ex)
                    return y_sym, None

            max_earn_workers = min(8, len(uncached_earnings))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_earn_workers) as executor:
                for y_sym, ed_val in executor.map(_fetch_earnings_one, uncached_earnings):
                    earnings_map[y_sym] = ed_val
                    _set_cached_earnings_date(y_sym, ed_val)

        for symbol in symbols:
            try:
                yahoo_symbol = symbol_map[symbol]
                data = batch_quotes_data.get(yahoo_symbol)

                if not data or data.get("price") is None:
                    self.logger.warning(
                        f"Sin precio para {symbol} (Yahoo: {yahoo_symbol})"
                    )
                    results[symbol] = Quote(status=QuoteStatus.UNAVAILABLE)
                    continue

                exchange = self._get_exchange_from_symbol(symbol)
                freshness_config = FRESHNESS_PER_EXCHANGE.get(
                    exchange, FreshnessConfig()
                )
                quote_ts = data["quote_timestamp"] or datetime.now(timezone.utc)
                if quote_ts.tzinfo is None:
                    quote_ts = quote_ts.replace(tzinfo=timezone.utc)
                status = freshness_config.freshness_state_naive(quote_ts)

                results[symbol] = Quote(
                    price=data["price"],
                    previous_close=data["previous_close"],
                    quote_timestamp=quote_ts,
                    fetched_at=datetime.now(timezone.utc),
                    provider="Yahoo",
                    status=status,
                    earnings_date=earnings_map.get(yahoo_symbol),
                )

            except Exception as e:
                self.logger.error(f"Error fetching {symbol}: {e}")
                results[symbol] = Quote(
                    status=QuoteStatus.ERROR,
                    error_message=str(e),
                )

        return results