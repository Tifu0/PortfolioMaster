from __future__ import annotations

import csv
from typing import Optional, Tuple

import pandas as pd
from openpyxl import load_workbook


def _detect_delimiter(sample: str) -> str:
    """Pick comma or semicolon from a CSV sample."""
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        if dialect.delimiter in {",", ";"}:
            return dialect.delimiter
    except csv.Error:
        pass
    first_line = sample.splitlines()[0] if sample.splitlines() else sample
    return ";" if first_line.count(";") > first_line.count(",") else ","


def _read_csv(file_path: str) -> pd.DataFrame:
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error: Optional[Exception] = None
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding, newline="") as handle:
                sample = handle.read(8192)
            delimiter = _detect_delimiter(sample)
            df = pd.read_csv(
                file_path,
                sep=delimiter,
                encoding=encoding,
                dtype=str,
            )
            # Safety net: semicolon assumed but the file is comma-separated.
            if df.shape[1] == 1 and "," in str(df.columns[0]):
                df = pd.read_csv(
                    file_path,
                    sep=",",
                    encoding=encoding,
                    dtype=str,
                )
            df.columns = [str(col).strip() for col in df.columns]
            return df
        except Exception as exc:
            last_error = exc
            continue
    raise last_error or ValueError("No se pudo leer el CSV")


def parse_spreadsheet(file_path: str, original_filename: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Parse a spreadsheet file (Excel or CSV) into a pandas DataFrame.

    Args:
        file_path: Path to the uploaded file
        original_filename: Name of the file as uploaded by the user

    Returns:
        (DataFrame, error_message) - DataFrame on success, or (None, error) on failure
    """
    try:
        if original_filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
            wb = load_workbook(file_path, read_only=True, data_only=True)
            try:
                ws = wb.active
                if ws is None:
                    return None, "La hoja de cálculo está vacía o no tiene hojas activas."
                data = ws.values
                cols = next(data, None)
                if cols is None:
                    return None, "El archivo Excel está vacío."
                df = pd.DataFrame(data, columns=cols)
                df.columns = [str(col).strip() if col is not None else "" for col in df.columns]
            finally:
                wb.close()
        elif original_filename.lower().endswith(".csv"):
            df = _read_csv(file_path)
        else:
            return None, "Formato de archivo no soportado"
        return df, None
    except Exception as e:
        return None, str(e)
