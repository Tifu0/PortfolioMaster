"""Canonical, pure safe-parsing helpers shared across core, ingest, DB, and API layers."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

_BLANK_MARKERS = frozenset({"", "nan", "none", "nat", "<na>"})
_TRUE_MARKERS = frozenset({"1", "true", "t", "yes", "y", "si", "sí", "s", "on"})
_FALSE_MARKERS = frozenset({"0", "false", "f", "no", "n", "off"})
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d")


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().lower() in _BLANK_MARKERS
    return False


def parse_decimal(
    value: Any,
    *,
    positive_only: bool = False,
    allow_zero: bool = True,
) -> Optional[Decimal]:
    """Convert numeric or EU/US formatted strings to finite Decimal, or None when invalid."""
    if value is None or isinstance(value, bool):
        return None

    result: Optional[Decimal] = None
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        result = value
    elif isinstance(value, (int, float)):
        try:
            d = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if d.is_nan() or d.is_infinite():
            return None
        result = d
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        text = text.replace(" ", "").replace("%", "")
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")  # European: 1.147,21
            else:
                text = text.replace(",", "")  # US: 1,147.21
        elif "," in text:
            text = text.replace(",", ".")
        try:
            d = Decimal(text)
        except (InvalidOperation, ValueError):
            return None
        if d.is_nan() or d.is_infinite():
            return None
        result = d

    if result is None:
        return None
    if positive_only and result <= 0:
        return None
    if not allow_zero and result == 0:
        return None
    return result


def parse_positive_decimal(value: Any) -> Optional[Decimal]:
    """Convert value to a strictly positive finite Decimal (> 0), or None."""
    return parse_decimal(value, positive_only=True)


def parse_date(value: Any) -> Optional[date]:
    """Parse date, datetime, ISO-8601, or common regional date strings into date."""
    if _is_blank_value(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw = str(value).strip()
    if raw.lower() in _BLANK_MARKERS:
        return None

    iso_candidate = raw.split("T")[0].split(" ")[0].strip()
    try:
        return date.fromisoformat(iso_candidate)
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_optional_iso_date(raw: Optional[str], field_name: str) -> Optional[date]:
    """Strictly parse an optional YYYY-MM-DD ISO string or raise ValueError."""
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"Invalid ISO date format for '{field_name}': expected YYYY-MM-DD"
        ) from exc


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse datetime, date, ISO-8601, or SQLite timestamp strings."""
    if _is_blank_value(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def parse_bool(
    value: Any,
    *,
    default: bool = True,
    empty_as_false: bool = False,
) -> bool:
    """Parse boolean values from native bools, numbers, or multilingual strings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isnan(value):
        return default
    text = str(value).strip().lower()
    if text in _BLANK_MARKERS:
        return False if (empty_as_false and text == "") else default
    if text in _TRUE_MARKERS:
        return True
    if text in _FALSE_MARKERS:
        return False
    return default


def clean_str(value: Any) -> str:
    """Convert nullable/NaN database or dataframe values to trimmed strings."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def clean_opt_str(value: Any) -> Optional[str]:
    """Convert nullable/NaN values to trimmed string or None."""
    cleaned = clean_str(value)
    return cleaned if cleaned else None


def safe_float(value: Any) -> Optional[float]:
    """Convert numeric values to finite float, filtering None, NaN, and Inf."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
        return None if (math.isnan(num) or math.isinf(num)) else num
    except (ValueError, TypeError):
        return None


def positive_float(value: Any, *, ndigits: int = 4) -> Optional[float]:
    """Convert value to rounded positive float (> 0) or None."""
    num = safe_float(value)
    if num is None or num <= 0:
        return None
    return round(num, ndigits)
