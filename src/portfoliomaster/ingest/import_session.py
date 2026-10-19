from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional, Tuple

import pandas as pd

from ..core.calculations import _to_decimal
from ..core.config import YAHOO_SUFFIXES, get_yahoo_suffix
from ..core.models import Exchange, Instrument
from .columns import map_columns
from .normalizer import normalize
from .parser import parse_spreadsheet
from .validator import detect_duplicates, validate_row


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "nat", "<na>"}


def _cell_str(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _cell_bool(value: Any, default: bool = True) -> bool:
    if _is_blank(value):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "si", "sí", "s"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return default


def _cell_date(value: Any) -> Optional[date]:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def import_spreadsheet(
    file_path: str, original_filename: str
) -> Tuple[List[Instrument], List[str], List[str], List[str]]:
    """
    Full import workflow: parse -> map -> normalize -> validate -> deduplicate.

    Returns:
        (instruments, errors, unresolved_symbols, warnings)
    """
    df, parse_error = parse_spreadsheet(file_path, original_filename)
    if parse_error:
        return [], [parse_error], [], []

    column_map = map_columns(list(df.columns))
    df = df.rename(columns=column_map)

    instruments = []
    row_errors = []
    unresolved_symbols = set()
    for idx, row in df.iterrows():
        row_dict = {key: row.get(key) for key in df.columns}
        row_dict["user_ticker"] = _cell_str(row_dict.get("user_ticker"))
        row_dict["company_name"] = _cell_str(row_dict.get("company_name"))
        row_dict["currency"] = _cell_str(row_dict.get("currency"))
        row_dict["comment"] = _cell_str(row_dict.get("comment"))

        if not row_dict["user_ticker"] and not row_dict["company_name"]:
            continue

        errors = validate_row(row_dict)
        if errors:
            row_errors.append(f"Fila {int(idx) + 2}: {errors}")
            continue

        inst = Instrument(
            user_ticker=row_dict["user_ticker"],
            company_name=row_dict["company_name"],
            analysis_date=_cell_date(row.get("analysis_date")),
            analysis_reference_price=_to_decimal(
                None
                if _is_blank(row.get("analysis_reference_price"))
                else row.get("analysis_reference_price")
            ),
            start_of_year_date=_cell_date(row.get("start_of_year_date")),
            start_of_year_price=_to_decimal(
                None
                if _is_blank(row.get("start_of_year_price"))
                else row.get("start_of_year_price")
            ),
            target_price=_to_decimal(
                None if _is_blank(row.get("target_price")) else row.get("target_price")
            ),
            currency=row_dict["currency"],
            comment=row_dict["comment"],
            active=_cell_bool(row.get("active"), default=True),
        )

        # --- Normalización del ticker ---
        norm_ticker, exchange = normalize(inst.user_ticker, inst.currency)

        # Aplicar sufijo Yahoo según el prefijo, exchange o divisa (US no lleva sufijo).
        # Evita duplicar el sufijo si ya venía incluido.
        suffix = get_yahoo_suffix(inst.user_ticker, exchange, inst.currency)
        if suffix and not norm_ticker.upper().endswith(suffix.upper()):
            provider_symbol = f"{norm_ticker}{suffix}"
        else:
            provider_symbol = norm_ticker

        # Asignar antes de usar los valores para registrar no resueltos.
        inst.provider_symbol = provider_symbol
        inst.exchange = exchange

        # Registrar símbolos no resueltos usando el ticker original del usuario
        # (es lo que el usuario reconoce y puede corregir en la hoja).
        if exchange == Exchange.UNKNOWN:
            unresolved_symbols.add(inst.user_ticker)

        instruments.append(inst)

    warnings = [
        f"Ticker duplicado: {ticker}"
        for ticker in detect_duplicates(instruments)
    ]

    return instruments, row_errors, list(unresolved_symbols), warnings