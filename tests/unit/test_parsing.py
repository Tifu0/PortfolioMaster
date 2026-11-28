"""Unit tests for canonical safe parsing utilities in portfoliomaster.core.parsing."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from portfoliomaster.core.parsing import (
    clean_opt_str,
    clean_str,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_decimal,
    parse_optional_iso_date,
    parse_positive_decimal,
    positive_float,
    safe_float,
)


def test_parse_decimal_supports_eu_us_percent_and_rejects_invalid():
    assert parse_decimal("1.147,21") == Decimal("1147.21")
    assert parse_decimal("1,147.21") == Decimal("1147.21")
    assert parse_decimal("166,45") == Decimal("166.45")
    assert parse_decimal(" 4,5 % ") == Decimal("4.5")
    assert parse_decimal(0) == Decimal("0")
    assert parse_decimal(-5) == Decimal("-5")
    assert parse_decimal(True) is None
    assert parse_decimal(float("nan")) is None
    assert parse_decimal(float("inf")) is None
    assert parse_decimal("NaN") is None
    assert parse_decimal("") is None
    assert parse_decimal("not-a-number") is None


def test_parse_positive_decimal_and_allow_zero_bounds():
    assert parse_positive_decimal("12.34") == Decimal("12.34")
    assert parse_positive_decimal("0") is None
    assert parse_positive_decimal("-1.5") is None
    assert parse_decimal("0", allow_zero=False) is None
    assert parse_decimal("-1", positive_only=True) is None


def test_parse_date_and_optional_iso_date():
    assert parse_date("2026-01-15") == date(2026, 1, 15)
    assert parse_date("2026-01-15T10:30:00+00:00") == date(2026, 1, 15)
    assert parse_date("15/01/2026") == date(2026, 1, 15)
    assert parse_date("15-01-2026") == date(2026, 1, 15)
    assert parse_date(datetime(2026, 2, 3, 14, 0, tzinfo=timezone.utc)) == date(2026, 2, 3)
    assert parse_date("NaT") is None
    assert parse_date("") is None
    assert parse_date("invalid-date") is None

    assert parse_optional_iso_date("2026-03-01", "analysis_date") == date(2026, 3, 1)
    assert parse_optional_iso_date("  ", "analysis_date") is None
    with pytest.raises(ValueError, match="analysis_date"):
        parse_optional_iso_date("01/03/2026", "analysis_date")


def test_parse_datetime():
    assert parse_datetime("2026-01-15 12:30:00") == datetime(2026, 1, 15, 12, 30, 0)
    assert parse_datetime(date(2026, 1, 15)) == datetime(2026, 1, 15, 0, 0, 0)
    assert parse_datetime("bad") is None


def test_parse_bool_semantics():
    assert parse_bool(True) is True
    assert parse_bool(False) is False
    assert parse_bool("false") is False
    assert parse_bool("0") is False
    assert parse_bool("no") is False
    assert parse_bool("sí") is True
    assert parse_bool("si") is True
    assert parse_bool("1") is True
    assert parse_bool("", default=True) is True
    assert parse_bool("", empty_as_false=True) is False
    assert parse_bool(None, default=True, empty_as_false=True) is True


def test_string_and_float_cleaners():
    assert clean_str(None) == ""
    assert clean_str("nan") == ""
    assert clean_str("  AAPL ") == "AAPL"
    assert clean_opt_str("None") is None
    assert clean_opt_str("  USD ") == "USD"
    assert safe_float(Decimal("12.345")) == 12.345
    assert safe_float(float("nan")) is None
    assert safe_float(math.inf) is None
    assert positive_float("12.34567") == 12.3457
    assert positive_float(0) is None
    assert positive_float("bad") is None
