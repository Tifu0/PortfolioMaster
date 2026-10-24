"""Financial calculations.

Pure, deterministic math. All arithmetic uses Decimal to avoid binary
floating-point drift in percentage and price work. No external
dependencies and no network calls.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

from .config import DISPLAY_DECIMAL_PLACES, FreshnessConfig
from .models import CalculationResult, Quote

Number = Union[float, Decimal, int, str, None]

# Precomputed constants to avoid reallocations on row-by-row financial calculations
_DISPLAY_QUANTIZE = Decimal(10) ** -DISPLAY_DECIMAL_PLACES
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)


def _to_decimal(value: Number) -> Optional[Decimal]:
    """Convert a value to Decimal, returning None for missing/invalid input.

    Accepts Decimal directly, int/float (safe via str conversion), and
    strings in comma or dot decimal form, e.g. "166,45", "1.147,21",
    "1.5", "NaN", "-inf". Non-numeric strings and infinities yield None.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return value
    if isinstance(value, bool):  # bool is a subclass of int — reject it.
        return None
    if isinstance(value, (int, float)):
        d = Decimal(str(value))
        if d.is_nan() or d.is_infinite():
            return None
        return d
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # Tolerate thousands separators and both decimal styles.
            s = s.replace(" ", "").replace("%", "")
            if "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")  # European: 1.147,21
                else:
                    s = s.replace(",", "")  # US style: 1,147.21
            elif "," in s:
                s = s.replace(",", ".")
            d = Decimal(s)
        except (InvalidOperation, ValueError):
            return None
        if d.is_nan() or d.is_infinite():
            return None
        return d
    return None


def _safe_div(numerator: Decimal, denominator: Decimal) -> Optional[Decimal]:
    """Return numerator / denominator, or None if invalid / division by zero."""
    if denominator == _ZERO:
        return None
    try:
        return numerator / denominator
    except (InvalidOperation, ZeroDivisionError):
        return None


def _round(value: Optional[Decimal]) -> Optional[Decimal]:
    """Round a Decimal to display precision using half-up rounding."""
    if value is None:
        return None
    return value.quantize(_DISPLAY_QUANTIZE, rounding=ROUND_HALF_UP)


def _is_valid_price(value: Number) -> bool:
    """A price is valid when it converts to a positive finite number."""
    if isinstance(value, Decimal):
        return not (value.is_nan() or value.is_infinite()) and value > _ZERO
    d = _to_decimal(value)
    return d is not None and d > _ZERO


def daily_variation(
    latest_price: Number,
    previous_close: Number,
) -> CalculationResult:
    """(latest_price / previous_close - 1) * 100."""
    result = CalculationResult()

    price = _to_decimal(latest_price)
    close = _to_decimal(previous_close)

    result.price_valid = _is_valid_price(price)
    if close is None or price is None or not result.price_valid:
        return result

    daily = _safe_div(price - close, close)
    if daily is None:
        return result
    result.daily_variation = _round(daily * _HUNDRED)
    result.daily_variation_valid = True
    return result


def variation_since_analysis(
    latest_price: Number,
    analysis_reference_price: Number,
) -> CalculationResult:
    """(latest_price / analysis_reference_price - 1) * 100."""
    result = CalculationResult()

    price = _to_decimal(latest_price)
    ref = _to_decimal(analysis_reference_price)

    result.price_valid = _is_valid_price(price)
    if ref is None or price is None or not result.price_valid:
        return result

    ratio = _safe_div(price - ref, ref)
    if ratio is None:
        return result
    result.variation_since_analysis = _round(ratio * _HUNDRED)
    result.variation_since_analysis_valid = True
    return result


def ytd_variation(
    latest_price: Number,
    ytd_reference_price: Number,
) -> CalculationResult:
    """(latest_price / ytd_reference_price - 1) * 100."""
    result = CalculationResult()

    price = _to_decimal(latest_price)
    ref = _to_decimal(ytd_reference_price)

    result.price_valid = _is_valid_price(price)
    if ref is None or price is None or not result.price_valid or not _is_valid_price(ref):
        return result

    ratio = _safe_div(price - ref, ref)
    if ratio is None:
        return result
    result.ytd_variation = _round(ratio * _HUNDRED)
    result.ytd_variation_valid = True
    return result


def decline_to_target(
    target_price: Number,
    latest_price: Number,
) -> CalculationResult:
    """((target_price - latest_price) / latest_price) * 100."""
    result = CalculationResult()

    target = _to_decimal(target_price)
    price = _to_decimal(latest_price)

    result.price_valid = _is_valid_price(price)
    if target is None or price is None or not result.price_valid:
        return result

    decline = _safe_div(target - price, price)
    if decline is None:
        return result
    result.decline_to_target = _round(decline * _HUNDRED)
    result.decline_to_target_valid = True
    result.target_valid = True
    return result


def is_target_reached(
    latest_price: Number,
    target_price: Number,
    quote: Quote,
    freshness_config: FreshnessConfig,
) -> CalculationResult:
    """latest_price <= target_price, only when the quote is trustworthy.

    Returns a valid target_reached flag only if both prices are valid and
    the quote status is fresh enough under the app's freshness rules.
    Missing or untrustworthy data yields an unavailable result rather
    than a fabricated alert.
    """
    result = CalculationResult()
    price = _to_decimal(latest_price)
    target = _to_decimal(target_price)
    if price is None or target is None:
        return result
    result.price_valid = price > _ZERO
    result.target_valid = target > _ZERO
    if not result.price_valid or not result.target_valid:
        return result
    if not quote.status.is_usable_for_alerts(freshness_config):
        return result
    result.target_reached = price <= target
    result.target_reached_valid = True
    return result


def _is_valid_price(value: Number) -> bool:
    """A price is valid when it converts to a positive finite number."""
    d = _to_decimal(value)
    return d is not None and d > 0
