"""Calibration chart parser and validator.

A calibration chart always has three columns (owner decision 2026-10-17):

    Tank name | Dip/Ullage | Volume

Two upload shapes are accepted and normalised to those three columns:

* **Long** — one row per point, with an explicit tank-name column. This is the
  canonical shape and the one the template download produces.
* **Wide** — depths down the rows and one column per tank. This is how a barge
  or FSO calibration book is usually printed, so accepting it saves the user
  from re-keying a whole book into the long shape.

Both shapes are validated before anything is written: the tank name must match
a tank declared on the asset exactly, the numbers must be finite and
non-negative, no depth may repeat within a tank, and each tank needs at least
two points or nothing can be interpolated.

Charts are deliberately **not** bound by the 5,000-row master import ceiling
(owner decision 2026-10-17): a barge or FSO strapping table is routinely
25,000+ points and must upload in full. The ceiling used here is
``CALIBRATION_MAX_ROWS`` — far above any real book, and it exists only so a
runaway file cannot exhaust the container. Set it to ``0`` to lift it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import CALIBRATION_MAX_ROWS, CALIBRATION_MAX_UPLOAD_BYTES
from app.services.calibration_engine import CalibrationError, CalibrationPoint, normalise_curve
from app.services.master_import import normalise_header, read_master_import
from app.utils.units import (
    to_canonical_dip,
    to_canonical_volume,
)

# Ceiling on calibration *points*, not on file rows: a wide layout expands one
# file row into one point per tank column. ``0`` means no ceiling.
MAX_CHART_ROWS = CALIBRATION_MAX_ROWS
MAX_CHART_UPLOAD_BYTES = CALIBRATION_MAX_UPLOAD_BYTES
MIN_POINTS_PER_TANK = 2

# Header aliases. Real calibration books label these columns many ways, so the
# parser folds them onto the three canonical fields.
_TANK_HEADERS = {
    "tank_name",
    "tank",
    "tankname",
    "tank_no",
    "tank_number",
    "compartment",
    "compartment_name",
    "comp",
}
_DIP_HEADERS = {
    "dip_ullage",
    "dipullage",
    "dip",
    "dips",
    "ullage",
    "innage",
    "outage",
    "gauge",
    "gauging",
    "level",
    "depth",
    "height",
    "dip_cm",
    "dip_mm",
    "dip_m",
    "ullage_cm",
}
_VOLUME_HEADERS = {
    "volume",
    "vol",
    "volumes",
    "capacity",
    "quantity",
    "qty",
    "volume_bbl",
    "volume_l",
    "volume_kl",
    "volume_litres",
    "volume_liters",
    "bbl",
    "barrels",
    "litres",
    "liters",
    "kl",
}

# Depth headers that also name their unit, used when the upload omits a unit.
_UNIT_FROM_DIP_HEADER = {
    "dip_cm": "cm",
    "dip_mm": "mm",
    "dip_m": "m",
    "ullage_cm": "cm",
}
_UNIT_FROM_VOLUME_HEADER = {
    "volume_bbl": "bbl",
    "bbl": "bbl",
    "barrels": "bbl",
    "volume_l": "l",
    "litres": "l",
    "liters": "l",
    "volume_litres": "l",
    "volume_liters": "l",
    "volume_kl": "kl",
    "kl": "kl",
}


@dataclass
class ParsedRow:
    """One validated calibration point."""

    row_number: int
    tank_name: str
    dip_cm: float
    volume_bbl: float
    source_dip_value: float
    source_volume_value: float
    layout: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ChartParseResult:
    """Everything the caller needs to preview or commit a chart."""

    filename: str
    file_format: str
    layout: str
    columns_detected: list[str]
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: list[dict]
    tanks_found: list[str]
    missing_columns: list[str]
    message: str
    implied_dip_unit: str | None = None
    implied_volume_unit: str | None = None


def _parse_number(value) -> float | None:
    """Parse a spreadsheet number, tolerating thousands separators and units."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None  # reject NaN
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "").replace(" ", "")
    for suffix in ("bbl", "kl", "l", "cm", "mm", "m"):
        if text.lower().endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _detect_columns(headers: list[str]) -> tuple[str | None, str | None, str | None, str, list[str]]:
    """Locate the tank, dip and volume columns; report the layout found."""
    normalised = [normalise_header(header) for header in headers]

    tank_column = next((name for name in normalised if name in _TANK_HEADERS), None)
    dip_column = next((name for name in normalised if name in _DIP_HEADERS), None)
    volume_column = next((name for name in normalised if name in _VOLUME_HEADERS), None)

    if tank_column is not None and dip_column is not None and volume_column is not None:
        return tank_column, dip_column, volume_column, "long", normalised

    # Wide layout: a depth column plus one column per tank.
    if dip_column is not None:
        tank_columns = [
            name
            for name in normalised
            if name and name not in {dip_column, volume_column} and name not in _DIP_HEADERS
        ]
        if tank_columns:
            return tank_column, dip_column, None, "wide", normalised

    return tank_column, dip_column, volume_column, "long", normalised


def parse_calibration_chart(
    content: bytes,
    filename: str,
    *,
    tank_names: list[str],
    dip_unit: str,
    volume_unit: str,
    measurement_basis: str = "Dip",
) -> ChartParseResult:
    """Read, validate and convert a calibration chart into canonical rows.

    ``tank_names`` are the tanks declared on the asset. A row whose tank name is
    not in that list is an error, because the chart would then describe a
    compartment the asset does not have.
    """
    # ``or None`` turns the configured ``0`` (no ceiling) into "read the whole
    # file", which is what a 25,000-point calibration book needs.
    table = read_master_import(
        content,
        filename,
        max_rows=MAX_CHART_ROWS or None,
        max_bytes=MAX_CHART_UPLOAD_BYTES or None,
    )
    columns = table["columns"]

    if not columns:
        return ChartParseResult(
            filename=filename,
            file_format=table["format"],
            layout="long",
            columns_detected=[],
            total_rows=0,
            valid_rows=0,
            invalid_rows=0,
            rows=[],
            tanks_found=[],
            missing_columns=["tank_name", "dip_ullage", "volume"],
            message="The file has no readable header row.",
        )

    tank_column, dip_column, volume_column, layout, normalised_headers = _detect_columns(columns)

    implied_dip_unit = _UNIT_FROM_DIP_HEADER.get(dip_column or "")
    implied_volume_unit = _UNIT_FROM_VOLUME_HEADER.get(volume_column or "")

    missing: list[str] = []
    if dip_column is None:
        missing.append("dip_ullage")
    if layout == "long" and tank_column is None:
        missing.append("tank_name")
    if layout == "long" and volume_column is None:
        missing.append("volume")

    if missing:
        return ChartParseResult(
            filename=filename,
            file_format=table["format"],
            layout=layout,
            columns_detected=columns,
            total_rows=len(table["rows"]),
            valid_rows=0,
            invalid_rows=len(table["rows"]),
            rows=[],
            tanks_found=[],
            missing_columns=missing,
            message="Missing required columns: " + ", ".join(missing),
            implied_dip_unit=implied_dip_unit,
            implied_volume_unit=implied_volume_unit,
        )

    known_tanks = {str(name).strip().casefold(): str(name).strip() for name in tank_names}
    canonical_tank_names = {name.casefold(): name for name in known_tanks.values()}

    parsed: list[ParsedRow] = []
    errors: list[dict] = []

    if layout == "long":
        for raw in table["rows"]:
            row_number = raw["row_number"]
            raw_tank = str(raw.get(tank_column, "") or "").strip()
            dip_value = _parse_number(raw.get(dip_column))
            volume_value = _parse_number(raw.get(volume_column))
            row_errors: list[str] = []

            if not raw_tank:
                row_errors.append("Tank name is required")
            elif raw_tank.casefold() not in known_tanks:
                row_errors.append(
                    f"Tank '{raw_tank}' is not declared on this asset. "
                    f"Declared tanks: {', '.join(sorted(canonical_tank_names.values())) or 'none'}"
                )
            if dip_value is None:
                row_errors.append(f"Dip/Ullage is not a valid number ('{raw.get(dip_column, '')}')")
            elif dip_value < 0:
                row_errors.append("Dip/Ullage cannot be negative")
            if volume_value is None:
                row_errors.append(f"Volume is not a valid number ('{raw.get(volume_column, '')}')")
            elif volume_value < 0:
                row_errors.append("Volume cannot be negative")

            if row_errors:
                errors.append(
                    {
                        "row_number": row_number,
                        "layout": "long",
                        "tank_name": raw_tank,
                        "dip_value": raw.get(dip_column, ""),
                        "volume_value": raw.get(volume_column, ""),
                        "valid": False,
                        "errors": row_errors,
                    }
                )
                continue

            parsed.append(
                ParsedRow(
                    row_number=row_number,
                    tank_name=known_tanks[raw_tank.casefold()],
                    dip_cm=round(to_canonical_dip(dip_value, dip_unit), 4),
                    volume_bbl=round(to_canonical_volume(volume_value, volume_unit), 6),
                    source_dip_value=dip_value,
                    source_volume_value=volume_value,
                    layout="long",
                )
            )
    else:
        # Wide layout: every non-depth column is a tank.
        depth_key = dip_column
        tank_columns = [
            name
            for name in normalised_headers
            if name and name != depth_key and name not in _DIP_HEADERS
        ]
        for raw in table["rows"]:
            row_number = raw["row_number"]
            dip_value = _parse_number(raw.get(depth_key))
            if dip_value is None:
                errors.append(
                    {
                        "row_number": row_number,
                        "layout": "wide",
                        "tank_name": "",
                        "dip_value": raw.get(depth_key, ""),
                        "volume_value": "",
                        "valid": False,
                        "errors": [f"Dip/Ullage is not a valid number ('{raw.get(depth_key, '')}')"],
                    }
                )
                continue
            if dip_value < 0:
                errors.append(
                    {
                        "row_number": row_number,
                        "layout": "wide",
                        "tank_name": "",
                        "dip_value": raw.get(depth_key, ""),
                        "volume_value": "",
                        "valid": False,
                        "errors": ["Dip/Ullage cannot be negative"],
                    }
                )
                continue

            for column in tank_columns:
                cell = raw.get(column)
                if cell is None or str(cell).strip() == "":
                    continue  # a tank may legitimately have no row at this depth
                volume_value = _parse_number(cell)
                label = str(column).replace("_", " ").strip()
                if volume_value is None:
                    errors.append(
                        {
                            "row_number": row_number,
                            "layout": "wide",
                            "tank_name": label,
                            "dip_value": dip_value,
                            "volume_value": cell,
                            "valid": False,
                            "errors": [f"Volume for tank '{label}' is not a valid number"],
                        }
                    )
                    continue
                if volume_value < 0:
                    errors.append(
                        {
                            "row_number": row_number,
                            "layout": "wide",
                            "tank_name": label,
                            "dip_value": dip_value,
                            "volume_value": cell,
                            "valid": False,
                            "errors": [f"Volume for tank '{label}' cannot be negative"],
                        }
                    )
                    continue
                if column.casefold() not in known_tanks and column not in known_tanks:
                    errors.append(
                        {
                            "row_number": row_number,
                            "layout": "wide",
                            "tank_name": label,
                            "dip_value": dip_value,
                            "volume_value": cell,
                            "valid": False,
                            "errors": [
                                f"Column '{label}' is not a tank declared on this asset. "
                                f"Declared tanks: {', '.join(sorted(canonical_tank_names.values())) or 'none'}"
                            ],
                        }
                    )
                    continue
                resolved = known_tanks.get(column.casefold()) or known_tanks.get(column)
                parsed.append(
                    ParsedRow(
                        row_number=row_number,
                        tank_name=resolved,
                        dip_cm=round(to_canonical_dip(dip_value, dip_unit), 4),
                        volume_bbl=round(to_canonical_volume(volume_value, volume_unit), 6),
                        source_dip_value=dip_value,
                        source_volume_value=volume_value,
                        layout="wide",
                    )
                )

    # Cross-row rules: duplicate depth within a tank, and too few points to
    # interpolate. Both are checked per tank so one bad tank does not hide
    # another.
    by_tank: dict[str, list[ParsedRow]] = {}
    for row in parsed:
        by_tank.setdefault(row.tank_name, []).append(row)

    seen: set[tuple[str, float]] = set()
    for row in parsed:
        key = (row.tank_name.casefold(), row.dip_cm)
        if key in seen:
            errors.append(
                {
                    "row_number": row.row_number,
                    "layout": row.layout,
                    "tank_name": row.tank_name,
                    "dip_value": row.source_dip_value,
                    "volume_value": row.source_volume_value,
                    "valid": False,
                    "errors": [
                        f"Depth {row.source_dip_value:g} {dip_unit} is repeated for tank "
                        f"'{row.tank_name}'"
                    ],
                }
            )
        else:
            seen.add(key)

    for tank_name, rows in sorted(by_tank.items()):
        if len(rows) < MIN_POINTS_PER_TANK:
            errors.append(
                {
                    "row_number": rows[0].row_number,
                    "layout": rows[0].layout,
                    "tank_name": tank_name,
                    "dip_value": "",
                    "volume_value": "",
                    "valid": False,
                    "errors": [
                        f"Tank '{tank_name}' has only {len(rows)} point(s); at least "
                        f"{MIN_POINTS_PER_TANK} are needed to interpolate"
                    ],
                }
            )
            continue
        try:
            normalise_curve(
                [CalibrationPoint(row.dip_cm, row.volume_bbl) for row in rows]
            )
        except CalibrationError as exc:
            errors.append(
                {
                    "row_number": rows[0].row_number,
                    "layout": rows[0].layout,
                    "tank_name": tank_name,
                    "dip_value": "",
                    "volume_value": "",
                    "valid": False,
                    "errors": [str(exc)],
                }
            )

    # The ceiling counts calibration points, not file rows: the wide layout
    # expands one file row into one point per tank column. ``0`` disables it.
    if MAX_CHART_ROWS and len(parsed) > MAX_CHART_ROWS:
        errors.append(
            {
                "row_number": 0,
                "layout": layout,
                "tank_name": "",
                "dip_value": "",
                "volume_value": "",
                "valid": False,
                "errors": [
                    f"Chart has {len(parsed):,} calibration points, which exceeds the "
                    f"{MAX_CHART_ROWS:,}-point limit"
                ],
            }
        )

    # A chart is allowed to be very large, so the per-tank working sets are
    # released before the caller-facing rows are built. Without this a
    # 100,000-point upload holds the points, the grouping and the preview rows
    # at the same time.
    tanks_found = sorted(by_tank)
    point_count = len(parsed)
    tank_count = len(by_tank)
    by_tank.clear()
    seen.clear()

    preview_rows = [
        {
            "row_number": row.row_number,
            "layout": row.layout,
            "tank_name": row.tank_name,
            "dip_value": row.source_dip_value,
            "volume_value": row.source_volume_value,
            "dip_cm": row.dip_cm,
            "volume_bbl": row.volume_bbl,
            "valid": True,
            "errors": [],
        }
        for row in parsed
    ]
    parsed.clear()
    preview_rows.extend(errors)
    preview_rows.sort(key=lambda item: (item["row_number"], str(item.get("tank_name"))))

    total = point_count + len(errors)
    valid = point_count
    invalid = len(errors)

    if invalid:
        message = f"{invalid} row(s) failed validation. Fix every error before importing."
    elif valid == 0:
        message = "No calibration rows were found in the file."
    else:
        message = (
            f"{valid} point(s) across {tank_count} tank(s) ready to import "
            f"({dip_unit} -> cm, {volume_unit} -> bbl)"
        )

    return ChartParseResult(
        filename=filename,
        file_format=table["format"],
        layout=layout,
        columns_detected=columns,
        total_rows=total,
        valid_rows=valid,
        invalid_rows=invalid,
        rows=preview_rows,
        tanks_found=tanks_found,
        missing_columns=[],
        message=message,
        implied_dip_unit=implied_dip_unit,
        implied_volume_unit=implied_volume_unit,
    )
