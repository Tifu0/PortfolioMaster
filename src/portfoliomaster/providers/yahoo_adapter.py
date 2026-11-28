import inspect
import concurrent.futures
import logging
import math
import threading
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
import os
import tempfile
from typing import Dict, List, Optional, Any
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
from ..core.config import (
    FRESHNESS_PER_EXCHANGE,
    YAHOO_SUFFIXES,
    EXCHANGE_HINTS,
    PREFIX_TO_YAHOO_SUFFIX,
)

_THREAD_LOCAL = threading.local()


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
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

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

        if missing_symbols:
            def _fetch_one_symbol(y_sym: str) -> tuple[str, Dict[str, Any]]:
                try:
                    t = _create_ticker(y_sym)
                    return y_sym, self._extract_quote_data(t)
                except Exception as ex:
                    self.logger.debug(f"Error fetching quote for {y_sym}: {ex}")
                    return y_sym, {"price": None, "previous_close": None, "quote_timestamp": None}

            max_workers = min(12, len(missing_symbols))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                for y_sym, data in executor.map(_fetch_one_symbol, missing_symbols):
                    if data and data.get("price") is not None:
                        batch_quotes_data[y_sym] = data

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
                )

            except Exception as e:
                self.logger.error(f"Error fetching {symbol}: {e}")
                results[symbol] = Quote(
                    status=QuoteStatus.ERROR,
                    error_message=str(e),
                )

        return results