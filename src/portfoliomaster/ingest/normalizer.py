from typing import Tuple
from ..core.models import Exchange
from ..core.config import EXCHANGE_HINTS, YAHOO_SUFFIXES, CURRENCY_TO_EXCHANGE


def normalize(ticker: str, currency: str = "") -> Tuple[str, Exchange]:
    """
    Normalize a user-provided ticker to a provider-friendly symbol and exchange.

    Examples:
        "BME:VIS" -> ("VIS", Exchange.SPAIN)
        "EPA:RMS" -> ("RMS", Exchange.FRANCE)
        "LON:AZN" -> ("AZN", Exchange.UK)
        "AAPL" -> ("AAPL", Exchange.US)
        "IPH", currency="AUD" -> ("IPH", Exchange.AUSTRALIA)
    """
    if not ticker:
        return "", Exchange.UNKNOWN

    ticker_clean = ticker.strip()
    curr_clean = currency.strip().upper() if currency else ""

    if ":" in ticker_clean:
        prefix, symbol = ticker_clean.split(":", 1)
        prefix_clean = prefix.strip().upper()
        symbol_clean = symbol.strip()
        exchange = EXCHANGE_HINTS.get(prefix_clean)
        if exchange is not None:
            return symbol_clean, exchange
        return symbol_clean, Exchange.UNKNOWN

    # Sin prefijo: verificar si termina en .US
    upper_ticker = ticker_clean.upper()
    if upper_ticker.endswith(".US"):
        return ticker_clean[:-3], Exchange.US

    # Si ya tiene un sufijo Yahoo conocido (ej. RMS.PA, VIS.MC)
    for ex, suf in YAHOO_SUFFIXES.items():
        if suf and upper_ticker.endswith(suf):
            return ticker_clean, ex

    # Fallback por divisa (ej. IPH con divisa AUD -> AUSTRALIA)
    if curr_clean and curr_clean in CURRENCY_TO_EXCHANGE:
        return ticker_clean, CURRENCY_TO_EXCHANGE[curr_clean]

    return ticker_clean, Exchange.US
