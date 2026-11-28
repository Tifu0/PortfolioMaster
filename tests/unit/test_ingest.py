"""Unit tests for spreadsheet ingestion, Spanish column mapping, and ticker normalization."""

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


def test_spanish_decimal_parsing(tmp_path):
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("Ticker;Price\nBME:VIS;166,45\n", encoding="utf-8")
    df, err = parse_spreadsheet(str(csv_file), "test.csv")
    assert err is None
    assert str(df.iloc[0]["Price"]).replace(".", ",") in {"166,45", "166.45"}
    assert df.iloc[0]["Ticker"] == "BME:VIS"


def test_comma_separated_user_sheet_columns(tmp_path):
    csv_file = tmp_path / "watchlist.csv"
    csv_file.write_text(USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n", encoding="utf-8")
    df, err = parse_spreadsheet(str(csv_file), "watchlist.csv")
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


def test_import_user_csv_does_not_report_missing_ticker(tmp_path):
    extra = (
        '16/06/2026,BME:VIS,Viscofan SA,"62,30","9,5",EUR,nota,"60,00","-1,00%","-3,70%","-15,00%"'
    )
    csv_file = tmp_path / "watchlist.csv"
    csv_file.write_text(USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n" + extra + "\n", encoding="utf-8")

    instruments, errors, unresolved, warnings = import_spreadsheet(str(csv_file), "watchlist.csv")
    assert errors == []
    assert warnings == []
    assert len(instruments) == 2

    tmus, vis = instruments[0], instruments[1]
    assert tmus.user_ticker == "TMUS"
    assert tmus.company_name == "T-Mobile Us Inc"
    assert tmus.currency == "USD"
    assert tmus.analysis_reference_price == Decimal("166.45")
    assert tmus.target_price == Decimal("140")
    assert tmus.analysis_date.isoformat() == "2026-09-17"
    assert tmus.exchange == Exchange.US

    assert vis.user_ticker == "BME:VIS"
    assert vis.exchange == Exchange.SPAIN
    assert vis.target_price == Decimal("9.5")


def test_duplicate_tickers_are_warnings_not_errors(tmp_path):
    duplicate_row = (
        '18/09/2026,TMUS,T-Mobile Us Inc,"170,00",141,USD,segunda fila,'
        '"150,00","-1,00%","-2,00%","-6,00%"'
    )
    csv_file = tmp_path / "watchlist_dup.csv"
    csv_file.write_text(
        USER_CSV_HEADER + "\n" + USER_CSV_ROW + "\n" + duplicate_row + "\n",
        encoding="utf-8",
    )

    instruments, errors, unresolved, warnings = import_spreadsheet(str(csv_file), "watchlist_dup.csv")
    assert errors == []
    assert len(instruments) == 2
    assert any("TMUS" in warning for warning in warnings)


def test_normalizer():
    assert normalize("BME:VIS") == ("VIS", Exchange.SPAIN)
    assert normalize("EPA:RMS") == ("RMS", Exchange.FRANCE)
    assert normalize("IPH", currency="AUD") == ("IPH", Exchange.AUSTRALIA)
    assert normalize("AAPL") == ("AAPL", Exchange.US)
