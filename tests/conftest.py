import os
import pytest

# Ensure clean test environment isolation regardless of developer .env settings
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_JWT_SECRET"] = "test-supabase-jwt-secret-for-testing-purposes-only-32b"

from portfoliomaster.db.connection import init_db

@pytest.fixture(autouse=True)
def test_db_isolation(tmp_path, monkeypatch):
    """Isolate tests from the user's real portfolio.db database."""
    test_db_file = str(tmp_path / "test_portfolio.db")
    monkeypatch.setenv("PORTFOLIOMASTER_DB_PATH", test_db_file)
    init_db()
    yield test_db_file
