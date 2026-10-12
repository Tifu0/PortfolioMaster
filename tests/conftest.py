import os
import pytest
from portfoliomaster.db.connection import init_db

@pytest.fixture(autouse=True)
def test_db_isolation(tmp_path, monkeypatch):
    """Isolate tests from the user's real portfolio.db database."""
    test_db_file = str(tmp_path / "test_portfolio.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", test_db_file)
    init_db()
    yield test_db_file
