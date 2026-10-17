"""Application-wide defaults.

Values live here so the UI, calculations, provider adapter and refresh
engine all agree on thresholds and batch sizes. Nothing external is
imported so this file stays testable in isolation.
"""

import os
from pathlib import Path
from decimal import Decimal
from typing import Optional

# Attempt to load .env from project root or working directory
try:
    from dotenv import load_dotenv

    _root_env = Path(__file__).resolve().parents[3] / ".env"
    if _root_env.exists():
        load_dotenv(dotenv_path=_root_env)
    else:
        load_dotenv()
except ImportError:
    pass

from .models import FreshnessConfig, Exchange

# Financial calculations (CLAUDE.md section 6): rounding for display only.
DISPLAY_DECIMAL_PLACES: int = 2

# Freshness thresholds for QuoteStatus determination.
DEFAULT_DELAY_SECONDS: float = 60.0
DEFAULT_STALENESS_SECONDS: float = 2 * 24 * 60 * 60  # 48 hours

# Batch runner tuning. Start conservative and measure before increasing.
DEFAULT_BATCH_SIZE: int = 10
MAX_BATCH_SIZE: int = 100
MAX_RETRIES: int = 2
BASE_BACKOFF_SECONDS: float = 0.5
MAX_BACKOFF_SECONDS: float = 5.0

# Refresh scheduler.
DEFAULT_REFRESH_INTERVAL_SECONDS: float = 5 * 60  # 5 minutes
MIN_REFRESH_INTERVAL_SECONDS: float = 5  # safety floor in seconds


def get_refresh_interval() -> float:
    """Return the configured refresh interval in seconds from environment.

    Reads REFRESH_INTERVAL_SECONDS. If set <= 0, returns 0.0 (auto-refresh disabled).
    Enforces a minimum safety floor of MIN_REFRESH_INTERVAL_SECONDS (5s) for positive values.
    Defaults to DEFAULT_REFRESH_INTERVAL_SECONDS (300s).
    """
    raw = os.getenv("REFRESH_INTERVAL_SECONDS")
    if raw is not None and raw.strip():
        try:
            val = float(raw.strip())
            if val <= 0:
                return 0.0
            return max(float(MIN_REFRESH_INTERVAL_SECONDS), val)
        except ValueError:
            pass
    return float(DEFAULT_REFRESH_INTERVAL_SECONDS)


def get_batch_size() -> int:
    """Return the batch size for market data queries from environment.

    Reads REFRESH_BATCH_SIZE (or fallback BATCH_SIZE).
    Defaults to DEFAULT_BATCH_SIZE (10). Enforces a minimum of 1.
    """
    raw = os.getenv("REFRESH_BATCH_SIZE") or os.getenv("BATCH_SIZE")
    if raw is not None and raw.strip():
        try:
            val = int(raw.strip())
            return max(1, val)
        except ValueError:
            pass
    return DEFAULT_BATCH_SIZE

# Database.
DATABASE_FILENAME: str = "portfolio.db"

# App binding.
DEFAULT_BIND_ADDRESS: str = "127.0.0.1"
DEFAULT_PORT: int = 8501

# Provider / symbol normalization reference.
from typing import Optional

# Provider / symbol normalization reference.
# provider_symbol -> (exchange, currency_hint) discovered on first fetch.
EXCHANGE_HINTS: dict[str, Exchange] = {
    # US markets
    "NASDAQ": Exchange.US,
    "NYSE": Exchange.US,
    "CBOE": Exchange.US,
    "ARCX": Exchange.US,
    "AMEX": Exchange.US,
    "NYSEARCA": Exchange.US,
    "BATS": Exchange.US,
    "OTC": Exchange.US,
    "US": Exchange.US,
    # Spain
    "BME": Exchange.SPAIN,
    "MCE": Exchange.SPAIN,
    # France
    "EPA": Exchange.FRANCE,
    "PAR": Exchange.FRANCE,
    # UK
    "LSE": Exchange.UK,
    "LON": Exchange.UK,
    # Germany
    "ETR": Exchange.GERMANY,
    "XETRA": Exchange.GERMANY,
    "FRA": Exchange.GERMANY,
    "GER": Exchange.GERMANY,
    # Italy
    "BIT": Exchange.ITALY,
    "MIL": Exchange.ITALY,
    # Netherlands
    "AMS": Exchange.NETHERLANDS,
    # Belgium
    "BRU": Exchange.BELGIUM,
    "EBR": Exchange.BELGIUM,
    # Portugal
    "LIS": Exchange.PORTUGAL,
    "ELI": Exchange.PORTUGAL,
    "BVL": Exchange.PORTUGAL,
    # Switzerland
    "SWX": Exchange.SWITZERLAND,
    "VTX": Exchange.SWITZERLAND,
    "SIX": Exchange.SWITZERLAND,
    # Sweden
    "STO": Exchange.SWEDEN,
    "OMX": Exchange.SWEDEN,
    # Denmark
    "CPH": Exchange.DENMARK,
    "CSE": Exchange.DENMARK,
    # Norway
    "OSL": Exchange.NORWAY,
    "OSE": Exchange.NORWAY,
    # Finland
    "HEL": Exchange.FINLAND,
    # Poland
    "WSE": Exchange.POLAND,
    "WAR": Exchange.POLAND,
    # Austria
    "VIE": Exchange.AUSTRIA,
    "WBAG": Exchange.AUSTRIA,
    # Greece
    "ATH": Exchange.GREECE,
    # Ireland
    "ISE": Exchange.IRELAND,
    # Australia
    "ASX": Exchange.AUSTRALIA,
    # South Korea
    "KRX": Exchange.SOUTH_KOREA,
    "KOSDAQ": Exchange.SOUTH_KOREA,
    # Japan
    "TYO": Exchange.JAPAN,
    "TSEJ": Exchange.JAPAN,
    "JPX": Exchange.JAPAN,
    # Hong Kong
    "HKG": Exchange.HONG_KONG,
    "HKEX": Exchange.HONG_KONG,
    # Taiwan
    "TPE": Exchange.TAIWAN,
    "TWSE": Exchange.TAIWAN,
    # China
    "SHE": Exchange.CHINA,
    "SZSE": Exchange.CHINA,
    "SSE": Exchange.CHINA,
    "SHA": Exchange.CHINA,
    # India
    "NSE": Exchange.INDIA,
    "BSE": Exchange.INDIA,
    # Canada
    "TSX": Exchange.CANADA,
    "TSE": Exchange.CANADA,
    "TSXV": Exchange.CANADA,
    # Brazil
    "B3": Exchange.BRAZIL,
    "SAO": Exchange.BRAZIL,
    "BVMF": Exchange.BRAZIL,
    # Mexico
    "BMV": Exchange.MEXICO,
    # Argentina
    "BCBA": Exchange.ARGENTINA,
    # Singapore
    "SGX": Exchange.SINGAPORE,
    # New Zealand
    "NZX": Exchange.NEW_ZEALAND,
    # Turkey
    "BIST": Exchange.TURKEY,
    # Saudi Arabia
    "TADAWUL": Exchange.SAUDI_ARABIA,
    # Indonesia
    "IDX": Exchange.INDONESIA,
    # Malaysia
    "KLSE": Exchange.MALAYSIA,
    # Thailand
    "SET": Exchange.THAILAND,
    # Philippines
    "PSE": Exchange.PHILIPPINES,
}

# Prefijo de exchange específico -> sufijo Yahoo Finance
PREFIX_TO_YAHOO_SUFFIX: dict[str, str] = {
    # US (sin sufijo)
    "US": "", "NASDAQ": "", "NYSE": "", "AMEX": "", "NYSEARCA": "",
    "ARCX": "", "CBOE": "", "BATS": "", "OTC": "",
    # Europa
    "EPA": ".PA", "PAR": ".PA",           # Euronext Paris (Francia)
    "BME": ".MC", "MCE": ".MC",           # Bolsa de Madrid (España)
    "LSE": ".L",  "LON": ".L",            # London Stock Exchange (UK)
    "XETRA": ".DE", "FRA": ".DE", "ETR": ".DE", "GER": ".DE",  # Alemania
    "BIT": ".MI", "MIL": ".MI",           # Borsa Italiana (Italia)
    "AMS": ".AS",                         # Euronext Amsterdam (Países Bajos)
    "BRU": ".BR", "EBR": ".BR",           # Euronext Bruselas (Bélgica)
    "LIS": ".LS", "ELI": ".LS", "BVL": ".LS", # Euronext Lisboa (Portugal)
    "SWX": ".SW", "VTX": ".SW", "SIX": ".SW",  # Suiza
    "OMX": ".ST", "STO": ".ST",           # Estocolmo (Suecia)
    "CPH": ".CO", "CSE": ".CO",           # Copenhague (Dinamarca)
    "OSL": ".OL", "OSE": ".OL",           # Oslo (Noruega)
    "HEL": ".HE",                         # Helsinki (Finlandia)
    "WSE": ".WA", "WAR": ".WA",           # Varsovia (Polonia)
    "VIE": ".VI", "WBAG": ".VI",          # Viena (Austria)
    "ATH": ".AT",                         # Atenas (Grecia)
    "ISE": ".IR",                         # Irlanda
    # América
    "TSX": ".TO", "TSE": ".TO",           # Toronto (Canadá)
    "TSXV": ".V",                         # TSX Venture (Canadá)
    "BVC": ".CL",                         # Colombia
    "BMV": ".MX",                         # México
    "BCBA": ".BA",                        # Buenos Aires (Argentina)
    "B3": ".SA", "SAO": ".SA", "BVMF": ".SA", # Brasil
    # Asia / Pacífico
    "TSEJ": ".T", "JPX": ".T", "TYO": ".T",  # Tokio (Japón)
    "HKEX": ".HK", "HKG": ".HK",          # Hong Kong
    "SGX": ".SI",                         # Singapur
    "KRX": ".KS",                         # Corea (KOSPI)
    "KOSDAQ": ".KQ",
    "ASX": ".AX",                         # Australia
    "NSE": ".NS", "BSE": ".BO",           # India
    "TADAWUL": ".SR",                     # Arabia Saudí
    "BIST": ".IS",                        # Turquía
    "IDX": ".JK",                         # Indonesia
    "KLSE": ".KL",                        # Malasia
    "SET": ".BK",                         # Tailandia
    "PSE": ".PS",                         # Filipinas
    "TWSE": ".TW", "TPE": ".TW",          # Taiwán
    "SZSE": ".SZ", "SHE": ".SZ",          # China Shenzhen
    "SSE": ".SS", "SHA": ".SS",           # China Shanghai
    "NZX": ".NZ",                         # Nueva Zelanda
}

# Currency per exchange, when we cannot derive it from the instrument row.
EXCHANGE_CURRENCY: dict[Exchange, str] = {
    Exchange.US: "USD",
    Exchange.SPAIN: "EUR",
    Exchange.FRANCE: "EUR",
    Exchange.UK: "GBP",
    Exchange.GERMANY: "EUR",
    Exchange.ITALY: "EUR",
    Exchange.NETHERLANDS: "EUR",
    Exchange.BELGIUM: "EUR",
    Exchange.PORTUGAL: "EUR",
    Exchange.SWITZERLAND: "CHF",
    Exchange.SWEDEN: "SEK",
    Exchange.DENMARK: "DKK",
    Exchange.NORWAY: "NOK",
    Exchange.FINLAND: "EUR",
    Exchange.POLAND: "PLN",
    Exchange.AUSTRIA: "EUR",
    Exchange.GREECE: "EUR",
    Exchange.IRELAND: "EUR",
    Exchange.AUSTRALIA: "AUD",
    Exchange.SOUTH_KOREA: "KRW",
    Exchange.JAPAN: "JPY",
    Exchange.HONG_KONG: "HKD",
    Exchange.TAIWAN: "TWD",
    Exchange.CHINA: "CNY",
    Exchange.INDIA: "INR",
    Exchange.CANADA: "CAD",
    Exchange.BRAZIL: "BRL",
    Exchange.MEXICO: "MXN",
    Exchange.ARGENTINA: "ARS",
    Exchange.SINGAPORE: "SGD",
    Exchange.NEW_ZEALAND: "NZD",
    Exchange.TURKEY: "TRY",
    Exchange.SAUDI_ARABIA: "SAR",
    Exchange.INDONESIA: "IDR",
    Exchange.MALAYSIA: "MYR",
    Exchange.THAILAND: "THB",
    Exchange.PHILIPPINES: "PHP",
}

# Yahoo-specific symbol suffixes per exchange.
YAHOO_SUFFIXES: dict[Exchange, str] = {
    Exchange.US: "",
    Exchange.SPAIN: ".MC",
    Exchange.FRANCE: ".PA",
    Exchange.UK: ".L",
    Exchange.GERMANY: ".DE",
    Exchange.ITALY: ".MI",
    Exchange.NETHERLANDS: ".AS",
    Exchange.BELGIUM: ".BR",
    Exchange.PORTUGAL: ".LS",
    Exchange.SWITZERLAND: ".SW",
    Exchange.SWEDEN: ".ST",
    Exchange.DENMARK: ".CO",
    Exchange.NORWAY: ".OL",
    Exchange.FINLAND: ".HE",
    Exchange.POLAND: ".WA",
    Exchange.AUSTRIA: ".VI",
    Exchange.GREECE: ".AT",
    Exchange.IRELAND: ".IR",
    Exchange.AUSTRALIA: ".AX",
    Exchange.SOUTH_KOREA: ".KS",
    Exchange.JAPAN: ".T",
    Exchange.HONG_KONG: ".HK",
    Exchange.TAIWAN: ".TW",
    Exchange.CHINA: ".SS",
    Exchange.INDIA: ".NS",
    Exchange.CANADA: ".TO",
    Exchange.BRAZIL: ".SA",
    Exchange.MEXICO: ".MX",
    Exchange.ARGENTINA: ".BA",
    Exchange.SINGAPORE: ".SI",
    Exchange.NEW_ZEALAND: ".NZ",
    Exchange.TURKEY: ".IS",
    Exchange.SAUDI_ARABIA: ".SR",
    Exchange.INDONESIA: ".JK",
    Exchange.MALAYSIA: ".KL",
    Exchange.THAILAND: ".BK",
    Exchange.PHILIPPINES: ".PS",
}

# Divisas a Exchange (cuando el ticker no tiene prefijo, ej. IPH con AUD -> AUSTRALIA)
CURRENCY_TO_EXCHANGE: dict[str, Exchange] = {
    "USD": Exchange.US,
    "AUD": Exchange.AUSTRALIA,
    "GBX": Exchange.UK,
    "GBP": Exchange.UK,
    "CAD": Exchange.CANADA,
    "SEK": Exchange.SWEDEN,
    "DKK": Exchange.DENMARK,
    "NOK": Exchange.NORWAY,
    "CHF": Exchange.SWITZERLAND,
    "JPY": Exchange.JAPAN,
    "HKD": Exchange.HONG_KONG,
    "KRW": Exchange.SOUTH_KOREA,
    "TWD": Exchange.TAIWAN,
    "INR": Exchange.INDIA,
    "PLN": Exchange.POLAND,
    "BRL": Exchange.BRAZIL,
    "MXN": Exchange.MEXICO,
    "NZD": Exchange.NEW_ZEALAND,
    "SGD": Exchange.SINGAPORE,
    "TRY": Exchange.TURKEY,
    "SAR": Exchange.SAUDI_ARABIA,
    "IDR": Exchange.INDONESIA,
    "MYR": Exchange.MALAYSIA,
    "THB": Exchange.THAILAND,
    "PHP": Exchange.PHILIPPINES,
}

# Divisas a sufijo Yahoo (fallback cuando el ticker no tiene prefijo)
CURRENCY_TO_YAHOO_SUFFIX: dict[str, str] = {
    "USD": "",
    "AUD": ".AX",
    "GBX": ".L",
    "GBP": ".L",
    "CAD": ".TO",
    "SEK": ".ST",
    "DKK": ".CO",
    "NOK": ".OL",
    "CHF": ".SW",
    "JPY": ".T",
    "HKD": ".HK",
    "KRW": ".KS",
    "TWD": ".TW",
    "INR": ".NS",
    "PLN": ".WA",
    "BRL": ".SA",
    "MXN": ".MX",
    "NZD": ".NZ",
    "SGD": ".SI",
    "TRY": ".IS",
    "SAR": ".SR",
    "IDR": ".JK",
    "MYR": ".KL",
    "THB": ".BK",
    "PHP": ".PS",
}


def get_yahoo_suffix(
    ticker: str,
    exchange: Optional[Exchange] = None,
    currency: Optional[str] = None,
) -> str:
    """
    Determina el sufijo Yahoo Finance adecuado según el ticker (prefijo),
    exchange o divisa.
    """
    ticker_clean = ticker.strip().upper() if ticker else ""
    curr_clean = currency.strip().upper() if currency else ""

    # 1. Si el ticker tiene prefijo de exchange (ej. EPA:RMS -> .PA, SHE:002847 -> .SZ)
    if ":" in ticker_clean:
        prefix, _ = ticker_clean.split(":", 1)
        prefix = prefix.strip()
        if prefix in PREFIX_TO_YAHOO_SUFFIX:
            return PREFIX_TO_YAHOO_SUFFIX[prefix]

    # 2. Si se proporcionó un exchange conocido
    if exchange and exchange in YAHOO_SUFFIXES:
        return YAHOO_SUFFIXES[exchange]

    # 3. Fallback por divisa si no hay prefijo (ej. IPH con AUD -> .AX)
    if curr_clean and curr_clean in CURRENCY_TO_YAHOO_SUFFIX:
        return CURRENCY_TO_YAHOO_SUFFIX[curr_clean]

    return ""

# Freshness rules tuned per market so we do not call a closed foreign market
# a failure.
FRESHNESS_PER_EXCHANGE: dict[Exchange, FreshnessConfig] = {
    Exchange.US: FreshnessConfig(
        delay_seconds=90.0,
        staleness_seconds=4 * 24 * 60 * 60,
        allow_delayed_alerts=False,
        allow_stale_alerts=False,
    ),
    Exchange.SPAIN: FreshnessConfig(
        delay_seconds=120.0,
        staleness_seconds=2 * 24 * 60 * 60,
        allow_delayed_alerts=False,
        allow_stale_alerts=False,
    ),
    Exchange.UK: FreshnessConfig(
        delay_seconds=120.0,
        staleness_seconds=2 * 24 * 60 * 60,
        allow_delayed_alerts=False,
        allow_stale_alerts=False,
    ),
    Exchange.AUSTRALIA: FreshnessConfig(
        delay_seconds=120.0,
        staleness_seconds=2 * 24 * 60 * 60,
        allow_delayed_alerts=False,
        allow_stale_alerts=False,
    ),
    Exchange.SOUTH_KOREA: FreshnessConfig(
        delay_seconds=120.0,
        staleness_seconds=2 * 24 * 60 * 60,
        allow_delayed_alerts=False,
        allow_stale_alerts=False,
    ),
}
