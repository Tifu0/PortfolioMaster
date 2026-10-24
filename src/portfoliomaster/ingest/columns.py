"""Column mapping for spreadsheet import."""

from __future__ import annotations

import re
import unicodedata

# First alias match wins. Do not map the sheet's ACTIVO (company name) to
# the boolean `active` flag.
COLUMN_MAPPING = {
    "user_ticker": ["Ticker", "TICKER", "Symbol", "Instrumento"],
    "company_name": ["Name", "Company", "Empresa", "Nombre", "ACTIVO"],
    "analysis_date": [
        "Analysis Date",
        "Fecha de Análisis",
        "Fecha del Análisis",
        "Fecha",
    ],
    "analysis_reference_price": [
        "Analysis Price",
        "Precio de Análisis",
        "Precio Compra Inicial",
        "COTIZACION FECHA ANALISIS",
        "COTIZACIÓN FECHA ANALISIS",
        "COTIZACION  FECHA ANALISIS",
    ],
    "start_of_year_date": [
        "Start of Year Date",
        "Fecha Inicio Año",
        "Fecha Inicio Ano",
        "Fecha YTD",
        "Fecha Inicio de Año",
    ],
    "start_of_year_price": [
        "Start of Year Price",
        "Precio Inicio Año",
        "Precio Inicio Ano",
        "Precio YTD",
        "Cotización Inicio Año",
        "Cotizacion Inicio Ano",
    ],
    "target_price": [
        "Target Price",
        "Precio Objetivo",
        "Precio Compra Objetivo",
        "PRECIO COMPRA",
    ],
    "currency": ["Currency", "Moneda", "Divisa"],
    "comment": [
        "Comment",
        "Comments",
        "Notes",
        "Note",
        "Comentarios",
        "Comentario",
        "COMENTARIO",
        "Nota",
        "Notas",
        "Descripcion",
        "Descripción",
        "DESCRIPCION",
        "DESCRIPCIÓN",
        "Description",
    ],
    "active": ["Active", "Is Active", "Activo S/N"],
}


def normalize_header(name: str | None) -> str:
    """Lowercase, strip accents, collapse punctuation/whitespace."""
    if name is None:
        return ""
    text = unicodedata.normalize("NFKD", str(name).strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Precompute normalized alias lookup table once at import time
_ALIAS_TO_INTERNAL: dict[str, str] = {}
for _internal_key, _aliases in COLUMN_MAPPING.items():
    for _alias in _aliases:
        _norm = normalize_header(_alias)
        if _norm and _norm not in _ALIAS_TO_INTERNAL:
            _ALIAS_TO_INTERNAL[_norm] = _internal_key


def map_columns(df_columns: list[str]) -> dict[str, str]:
    """Map user-provided column names to internal keys."""
    mapping: dict[str, str] = {}
    for col in df_columns:
        key = normalize_header(col)
        if key in _ALIAS_TO_INTERNAL and col not in mapping:
            mapping[col] = _ALIAS_TO_INTERNAL[key]
    return mapping
