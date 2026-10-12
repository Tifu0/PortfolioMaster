"""Validation for imported instrument data."""

from typing import List, Dict, Any
from ..core.models import Instrument

def validate_row(row: Dict[str, Any]) -> List[str]:
    """Validate a single imported row. Returns list of error messages."""
    errors = []
    if not row.get("user_ticker"):
        errors.append("Missing user_ticker")
    return errors

def detect_duplicates(instruments: List[Instrument]) -> List[str]:
    """Return list of tickers that appear more than once."""
    seen = set()
    duplicates = set()
    for inst in instruments:
        if inst.user_ticker in seen:
            duplicates.add(inst.user_ticker)
        seen.add(inst.user_ticker)
    return list(duplicates)
