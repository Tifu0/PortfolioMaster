"""Root pytest configuration and global test environment isolation."""

import os

# Ensure clean test environment isolation regardless of developer .env settings
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_JWT_SECRET"] = "test-supabase-jwt-secret-for-testing-purposes-only-32b"
