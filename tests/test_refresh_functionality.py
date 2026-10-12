import pytest
from decimal import Decimal
from dataclasses import asdict, is_dataclass

from portfoliomaster.core.models import Quote, QuoteStatus, Instrument, Exchange
from portfoliomaster.providers.mock_provider import MockProvider
from portfoliomaster.providers.yahoo_adapter import YahooAdapter 
from portfoliomaster.refresh.batch_runner import BatchRunner
from portfoliomaster.db.repository import (
    upsert_quote,
    get_all_instruments,
    wipe_database,
    upsert_instrument,
)
from portfoliomaster.db.connection import init_db, get_connection


def _reset_db():
    conn = get_connection()
    conn.execute("DROP TABLE IF EXISTS quotes")
    conn.execute("DROP TABLE IF EXISTS instruments")
    conn.commit()
    conn.close()
    init_db()
    wipe_database()


def _dump_quote(symbol: str, quote) -> None:
    """Imprime toda la info disponible de un Quote de forma legible."""
    print(f"\n--- {symbol} ---")
    if quote is None:
        print("  (sin cotización)")
        return
    if is_dataclass(quote):
        data = asdict(quote)
    elif hasattr(quote, "__dict__"):
        data = vars(quote)
    else:
        data = {"repr": repr(quote)}

    for k, v in data.items():
        print(f"  {k}: {v!r}")
    print(f"  tipo: {type(quote).__name__}")


def test_refresh_functionality_with_mock_data():
    """Test original, determinista, con MockProvider."""
    _reset_db()

    inst1 = Instrument(user_ticker="AAPL", provider_symbol="AAPL", exchange=Exchange.US)
    upsert_instrument(inst1)

    mock_data = {"AAPL": Quote(price=Decimal("150.00"), status=QuoteStatus.FRESH)}
    provider = MockProvider(mock_data=mock_data)
    runner = BatchRunner(provider=provider, batch_size=10)

    instruments = get_all_instruments()
    symbols = [inst.provider_symbol for inst in instruments if inst.provider_symbol]
    quotes = runner.run(symbols)

    instrument_map = {inst.provider_symbol: inst.id for inst in instruments}
    for symbol, quote in quotes.items():
        quote.instrument_id = instrument_map.get(symbol)
        if quote.instrument_id:
            upsert_quote(quote)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT price FROM quotes WHERE instrument_id = ?",
        (instrument_map["AAPL"],),
    )
    price = cursor.fetchone()[0]
    conn.close()

    assert Decimal(str(price)) == Decimal("150.00")


def test_refresh_with_yfinance_prints_quote():
    """Igual que el anterior pero usando yfinance y haciendo print de la info."""
    _reset_db()

    inst1 = Instrument(user_ticker="AAPL", provider_symbol="AAPL", exchange=Exchange.US)
    upsert_instrument(inst1)

    # Proveedor real de yfinance (asegúrate de que la clase se instancie correctamente)
    provider = YahooAdapter() 
    runner = BatchRunner(provider=provider, batch_size=10)

    instruments = get_all_instruments()
    symbols = [inst.provider_symbol for inst in instruments if inst.provider_symbol]

    print("\n===== Consultando yfinance para:", symbols, "=====")
    quotes = runner.run(symbols)

    print("\n===== Info devuelta por yfinance =====")
    for symbol, quote in quotes.items():
        _dump_quote(symbol, quote)

    # Persistimos en BD
    instrument_map = {inst.provider_symbol: inst.id for inst in instruments}
    for symbol, quote in quotes.items():
        quote.instrument_id = instrument_map.get(symbol)
        if quote.instrument_id:
            upsert_quote(quote)

    # Releemos de BD y volvemos a imprimir
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT price, status FROM quotes WHERE instrument_id = ?",
        (instrument_map["AAPL"],),
    )
    row = cursor.fetchone()
    conn.close()

    print("\n===== Fila guardada en BD (quotes) =====")
    print("  price :", row[0] if row else None)
    print("  status:", row[1] if row else None)

    # Comprobación mínima
    assert "AAPL" in quotes, "yfinance no devolvió cotización para AAPL"
    assert quotes["AAPL"].price is not None
    if row:
        assert Decimal(str(row[0])) == Decimal(str(quotes["AAPL"].price))


def test_epa_rms_normalizes_to_paris_suffix():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("EPA:RMS") == "RMS.PA"

def test_bme_vis_normalizes_to_madrid_suffix():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("BME:VIS") == "VIS.MC"

def test_us_symbols_have_no_suffix():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("NASDAQ:AAPL") == "AAPL"
    assert adapter._normalize_symbol_for_yahoo("AAPL.US") == "AAPL"
    assert adapter._normalize_symbol_for_yahoo("AAPL") == "AAPL"

def test_already_suffixed_symbol_is_respected():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("RMS.PA") == "RMS.PA"
    assert adapter._normalize_symbol_for_yahoo("EPA:RMS.PA") == "RMS.PA"

def test_unknown_prefix_falls_back_to_bare_ticker():
    adapter = YahooAdapter()
    # No debe devolver "XYZ:RMS" (Yahoo no lo entiende)
    assert adapter._normalize_symbol_for_yahoo("XYZ:RMS") == "RMS"


def test_lon_azn_normalizes_to_london_l_suffix():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("LON:AZN") == "AZN.L"
    assert adapter._normalize_symbol_for_yahoo("LSE:AZN") == "AZN.L"


def test_she_normalizes_to_shenzhen_suffix():
    adapter = YahooAdapter()
    assert adapter._normalize_symbol_for_yahoo("SHE:002847") == "002847.SZ"


def test_get_yahoo_suffix_and_normalize_with_currency():
    from portfoliomaster.ingest.normalizer import normalize
    from portfoliomaster.core.config import get_yahoo_suffix

    ticker, ex = normalize("IPH", currency="AUD")
    assert ticker == "IPH"
    assert ex == Exchange.AUSTRALIA
    suffix = get_yahoo_suffix("IPH", ex, currency="AUD")
    assert suffix == ".AX"

    ticker, ex = normalize("EPA:RMS", currency="EUR")
    assert ticker == "RMS"
    assert ex == Exchange.FRANCE
    suffix = get_yahoo_suffix("EPA:RMS", ex, currency="EUR")
    assert suffix == ".PA"

    ticker, ex = normalize("LON:AZN", currency="GBX")
    assert ticker == "AZN"
    assert ex == Exchange.UK
    suffix = get_yahoo_suffix("LON:AZN", ex, currency="GBX")
    assert suffix == ".L"

    ticker, ex = normalize("AAPL", currency="USD")
    assert ticker == "AAPL"
    assert ex == Exchange.US
    suffix = get_yahoo_suffix("AAPL", ex, currency="USD")
    assert suffix == ""