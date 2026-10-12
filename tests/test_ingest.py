import os
import tempfile

from decimal import Decimal

from portfoliomaster.core.models import Exchange
from portfoliomaster.ingest.columns import map_columns
from portfoliomaster.ingest.import_session import import_spreadsheet
from portfoliomaster.ingest.normalizer import normalize
from portfoliomaster.ingest.parser import parse_spreadsheet


USER_CSV_HEADER = (
    "Fecha del Análisis,TICKER,ACTIVO,COTIZACION  FECHA ANALISIS,"
    "PRECIO COMPRA,Divisa,COMENTARIO,COTIZACIÓN ACTUAL,VARIACIÓN DIARIA,"
    "Varia % desde analisis hasta Hoy,PORCENTAJE DE CAÍDA NECESARIO"
)
USER_CSV_ROW = (
    '17/09/2026,TMUS,T-Mobile Us Inc,"166,45",140,USD,'
    'comienzo de la zona optima de compra,"148,58","-13,27%","-10,74%","-5,77%"'
)


def _write_csv(content: str) -> str:
    handle = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".csv", encoding="utf-8", newline=""
    )
    try:
        handle.write(content)
        return handle.name
    finally:
        handle.close()


def test_spanish_decimal_parsing():
    csv_content = "Ticker;Price\nBME:VIS;166,45\n"
    tmp_path = _write_csv(csv_content)
    try:
        df, err = parse_spreadsheet(tmp_path, "test.csv")
        assert err is None
        assert str(df.iloc[0]["Price"]).replace(".", ",") in {"166,45", "166.45"}
        assert df.iloc[0]["Ticker"] == "BME:VIS"
    finally:
        os.remove(tmp_path)


def test_comma_separated_user_sheet_columns():
    tmp_path = _write_csv(USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n")
    try:
        df, err = parse_spreadsheet(tmp_path, "watchlist.csv")
        assert err is None
        assert "TICKER" in df.columns
        mapping = map_columns(list(df.columns))
        assert mapping["TICKER"] == "user_ticker"
        assert mapping["ACTIVO"] == "company_name"
        assert mapping["Divisa"] == "currency"
        assert mapping["PRECIO COMPRA"] == "target_price"
        assert mapping["Fecha del Análisis"] == "analysis_date"
        assert mapping["COTIZACION  FECHA ANALISIS"] == "analysis_reference_price"
        assert mapping["COMENTARIO"] == "comment"
        assert "ACTIVO" not in {k: v for k, v in mapping.items() if v == "active"}
    finally:
        os.remove(tmp_path)


def test_import_user_csv_does_not_report_missing_ticker():
    extra = (
        '16/06/2026,BME:VIS,Viscofan SA,"62,30","9,5",EUR,nota,"60,00","-1,00%","-3,70%","-15,00%"'
    )
    content = USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n" + extra + "\n"
    tmp_path = _write_csv(content)
    try:
        instruments, errors, unresolved, warnings = import_spreadsheet(tmp_path, "watchlist.csv")
        assert errors == []
        assert warnings == []
        assert len(instruments) == 2
        tmus = instruments[0]
        assert tmus.user_ticker == "TMUS"
        assert tmus.company_name == "T-Mobile Us Inc"
        assert tmus.currency == "USD"
        assert tmus.analysis_reference_price == Decimal("166.45")
        assert tmus.target_price == Decimal("140")
        assert tmus.analysis_date.isoformat() == "2026-09-17"
        vis = instruments[1]
        assert vis.user_ticker == "BME:VIS"
        assert vis.exchange == Exchange.SPAIN
        assert vis.target_price == Decimal("9.5")
        # TMUS is a valid US ticker, it should have been processed
        # The original test expected "TMUS" in unresolved_symbols which seems wrong
        # given normalization now handles it as US exchange.
        assert tmus.user_ticker == "TMUS"
        assert tmus.exchange == Exchange.US
    finally:
        os.remove(tmp_path)


def test_duplicate_tickers_are_warnings_not_errors():
    duplicate_row = (
        '18/09/2026,TMUS,T-Mobile Us Inc,"170,00",141,USD,segunda fila,'
        '"150,00","-1,00%","-2,00%","-6,00%"'
    )
    content = USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n" + duplicate_row + "\n"
    tmp_path = _write_csv(content)
    try:
        instruments, errors, unresolved, warnings = import_spreadsheet(tmp_path, "watchlist.csv")
        assert errors == []
        assert len(instruments) == 2
        assert any("TMUS" in warning for warning in warnings)
    finally:
        os.remove(tmp_path)


def test_normalizer():
    ticker, exchange = normalize("BME:VIS")
    assert ticker == "VIS"
    assert exchange == Exchange.SPAIN

    ticker, exchange = normalize("EPA:RMS")
    assert ticker == "RMS"
    assert exchange == Exchange.FRANCE

    ticker, exchange = normalize("IPH", currency="AUD")
    assert ticker == "IPH"
    assert exchange == Exchange.AUSTRALIA

    ticker, exchange = normalize("AAPL")
    assert ticker == "AAPL"
    assert exchange == Exchange.US
