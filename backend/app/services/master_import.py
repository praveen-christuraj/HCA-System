"""Shared XLSX/CSV reader for the soft-coded master pages."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from openpyxl import load_workbook

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
SUPPORTED_SUFFIXES = {".csv", ".xlsx"}


def normalise_header(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-]+", "_", text)
    return re.sub(r"[^a-z0-9_]", "", text)


def _read_table(content: bytes, suffix: str) -> list[list[str]]:
    if suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sheet = workbook.active
            rows = []
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if row_number > MAX_IMPORT_ROWS + 1:
                    raise ValueError(f"File exceeds the {MAX_IMPORT_ROWS}-row import limit.")
                rows.append(["" if value is None else str(value).strip() for value in row])
            return rows
        finally:
            workbook.close()

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = content.decode("latin-1")
    rows = []
    for row_number, row in enumerate(csv.reader(io.StringIO(decoded)), start=1):
        if row_number > MAX_IMPORT_ROWS + 1:
            raise ValueError(f"File exceeds the {MAX_IMPORT_ROWS}-row import limit.")
        rows.append([str(value or "").strip() for value in row])
    return rows


def read_master_import(content: bytes, filename: str) -> dict:
    """Read an upload into normalized row dictionaries without changing data."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported file type. Use .xlsx or .csv.")
    if len(content) > MAX_IMPORT_BYTES:
        raise ValueError("File exceeds the 5 MB import limit.")

    try:
        table = _read_table(content, suffix)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The file could not be read. Check that it is a valid XLSX or CSV file.") from exc
    table = [row for row in table if any(str(cell or "").strip() for cell in row)]
    if not table:
        return {
            "filename": filename,
            "format": suffix.lstrip("."),
            "columns": [],
            "rows": [],
        }

    headers = [normalise_header(value) for value in table[0]]
    rows = []
    for row_number, values in enumerate(table[1:], start=2):
        rows.append(
            {
                "row_number": row_number,
                **{
                    header: str(values[index] or "").strip()
                    for index, header in enumerate(headers)
                    if header and index < len(values)
                },
            }
        )
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"File exceeds the {MAX_IMPORT_ROWS}-row import limit.")
    return {
        "filename": filename,
        "format": suffix.lstrip("."),
        "columns": [header for header in headers if header],
        "rows": rows,
    }
