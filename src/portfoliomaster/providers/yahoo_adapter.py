import yfinance as yf
from typing import Dict, List, Optional, Any
from .base import MarketDataProvider
from ..core.models import Quote, QuoteStatus, FreshnessConfig, Exchange
from ..core.config import (
    FRESHNESS_PER_EXCHANGE,
    YAHOO_SUFFIXES,
    EXCHANGE_HINTS,
    PREFIX_TO_YAHOO_SUFFIX,
    get_yahoo_suffix,
)
from datetime import datetime, date, timedelta
from decimal import Decimal
import logging
import math
import pandas as pd


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
            price = _fi_get(fi, "last_price", "lastPrice", "regularMarketPrice")
            previous_close = _fi_get(
                fi, "previous_close", "previousClose", "regularMarketPreviousClose"
            )
            qt = _fi_get(fi, "last_update", "lastUpdate")
            if qt is not None:
                if hasattr(qt, "to_pydatetime"):
                    quote_timestamp = qt.to_pydatetime()
                elif isinstance(qt, (int, float)):
                    quote_timestamp = datetime.fromtimestamp(qt)
                elif isinstance(qt, datetime):
                    quote_timestamp = qt
        except Exception as e:
            self.logger.debug(f"fast_info falló: {e}")

        # Fallback con history() si no tenemos precio
        if price is None:
            try:
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

        for symbol in symbols:
            try:
                yahoo_symbol = self._normalize_symbol_for_yahoo(symbol)

                self.logger.debug(
                    f"Consultando Yahoo Finance: {symbol} -> {yahoo_symbol}"
                )

                ticker = yf.Ticker(yahoo_symbol)
                data = self._extract_quote_data(ticker)

                if data["price"] is None:
                    self.logger.warning(
                        f"Sin precio para {symbol} (Yahoo: {yahoo_symbol})"
                    )
                    results[symbol] = Quote(status=QuoteStatus.UNAVAILABLE)
                    continue

                exchange = self._get_exchange_from_symbol(symbol)
                freshness_config = FRESHNESS_PER_EXCHANGE.get(
                    exchange, FreshnessConfig()
                )
                quote_ts = data["quote_timestamp"] or datetime.now()
                status = freshness_config.freshness_state_naive(quote_ts)

                results[symbol] = Quote(
                    price=data["price"],
                    previous_close=data["previous_close"],
                    quote_timestamp=quote_ts,
                    fetched_at=datetime.now(),
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

    @property
    def batch_supported(self) -> bool:
        return True

    @property
    def default_batch_size(self) -> int:
        return 10

    def fetch_historical_quote(
        self, symbol: str, target_date: date, window_days: int = 10
    ) -> Optional[tuple[Decimal, date]]:
        """Fetch historical close on or before target_date with lookback and resilient fallback."""
        yahoo_symbol = self._normalize_symbol_for_yahoo(symbol)
        try:
            t = yf.Ticker(yahoo_symbol)

            # 1. Historical lookback window
            start_str = (target_date - timedelta(days=window_days)).isoformat()
            end_str = (target_date + timedelta(days=1)).isoformat()
            hist = t.history(start=start_str, end=end_str)

            if not hist.empty and "Close" in hist:
                valid_rows = []
                for idx, row in hist.iterrows():
                    row_dt = idx.date() if hasattr(idx, "date") else idx.to_pydatetime().date()
                    val = row["Close"]
                    if row_dt <= target_date and pd.notna(val) and float(val) > 0:
                        valid_rows.append((float(val), row_dt))

                if valid_rows:
                    price, actual_dt = valid_rows[-1]
                    return Decimal(str(round(price, 4))), actual_dt

            # 2. Resilient fallback for today / closed market / weekends
            price = None
            actual_dt = target_date

            try:
                fi = getattr(t, "fast_info", None)
                if fi:
                    lp = _fi_get(fi, "last_price", "lastPrice", "regularMarketPrice")
                    if lp is not None and not math.isnan(float(lp)) and float(lp) > 0:
                        price = float(lp)
                    if price is None:
                        pc = _fi_get(fi, "previous_close", "previousClose", "regularMarketPreviousClose")
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
                return Decimal(str(round(price, 4))), actual_dt

        except Exception as e:
            self.logger.debug(f"fetch_historical_quote error for {symbol}: {e}")

        return None