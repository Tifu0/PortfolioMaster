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


def map_columns(df_columns: list[str]) -> dict[str, str]:
    """Map user-provided column names to internal keys."""
    alias_to_internal: dict[str, str] = {}
    for internal_key, aliases in COLUMN_MAPPING.items():
        for alias in aliases:
            key = normalize_header(alias)
            if key and key not in alias_to_internal:
                alias_to_internal[key] = internal_key

    mapping: dict[str, str] = {}
    for col in df_columns:
        key = normalize_header(col)
        if key in alias_to_internal and col not in mapping:
            mapping[col] = alias_to_internal[key]
    return mapping
