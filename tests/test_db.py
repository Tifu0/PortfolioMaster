from datetime import date
from decimal import Decimal

from portfoliomaster.core.models import Exchange, Instrument
from portfoliomaster.db.connection import get_connection, init_db
from portfoliomaster.db.repository import upsert_instrument


def test_db_init_and_upsert():
    init_db()

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

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_ticker, provider_symbol, analysis_reference_price, start_of_year_price, start_of_year_date, target_price "
        "FROM instruments WHERE user_ticker='AAPL'"
    )
    row = cursor.fetchone()
    count = cursor.execute("SELECT COUNT(*) FROM instruments WHERE user_ticker='AAPL'").fetchone()[0]
    conn.close()

    assert row is not None
    assert row[0] == "AAPL"
    assert row[1] == "AAPL.US"
    assert Decimal(str(row[2])) == Decimal("166.45")
    assert Decimal(str(row[3])) == Decimal("180.25")
    assert str(row[4]) == "2026-01-02"
    assert Decimal(str(row[5])) == Decimal("140")
    assert count == 1
