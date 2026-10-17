"""Measurement units and the conversion factors to the system canonical units.

Owner rule for calibration: the system calculates in **one** unit per quantity
regardless of the unit the calibration chart was supplied in.

* canonical dip/ullage unit: **cm**
* canonical volume unit:     **bbl**

Charts may be supplied in cm, mm or m for depth and in litres, kilolitres or
barrels for volume. Values are converted once, on the way in, and stored next to
the original supplied value so an auditor can always see both.

Conversion basis: 1 barrel (US petroleum) = 158.987294928 litres
= 0.158987294928 m3. This is the same constant OTMS used
(``BARREL_TO_CUBIC_METER = 0.158987294928``) so historical results reconcile.
"""

from __future__ import annotations

CANONICAL_DIP_UNIT = "cm"
CANONICAL_VOLUME_UNIT = "bbl"

LITERS_PER_BARREL = 158.987294928
CUBIC_METERS_PER_BARREL = 0.158987294928
CENTIMETERS_PER_METER = 100.0
MILLIMETERS_PER_CENTIMETER = 10.0
LITERS_PER_KILOLITER = 1000.0

# Depth units accepted on a calibration chart, with the factor that converts a
# value expressed in that unit into the canonical centimetre.
DIP_UNIT_FACTORS: dict[str, float] = {
    "cm": 1.0,
    "mm": 1.0 / MILLIMETERS_PER_CENTIMETER,  # 1 mm = 0.1 cm
    "m": CENTIMETERS_PER_METER,              # 1 m  = 100 cm
}

# Volume units accepted on a calibration chart, with the factor that converts a
# value expressed in that unit into the canonical barrel.
VOLUME_UNIT_FACTORS: dict[str, float] = {
    "bbl": 1.0,
    "l": 1.0 / LITERS_PER_BARREL,
    "kl": LITERS_PER_KILOLITER / LITERS_PER_BARREL,
}

DIP_UNITS: tuple[str, ...] = ("cm", "mm", "m")
VOLUME_UNITS: tuple[str, ...] = ("l", "kl", "bbl")

# Presentation labels. The stored value is always the lowercase unit code.
DIP_UNIT_LABELS: dict[str, str] = {"cm": "Centimetres (cm)", "mm": "Millimetres (mm)", "m": "Metres (m)"}
VOLUME_UNIT_LABELS: dict[str, str] = {
    "l": "Litres (L)",
    "kl": "Kilolitres (kL)",
    "bbl": "Barrels (bbl)",
}

MEASUREMENT_BASES = ("Dip", "Ullage")

# Aliases accepted in a spreadsheet header or a unit cell.
_DIP_UNIT_ALIASES: dict[str, str] = {
    "cm": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "cms": "cm",
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
}

_VOLUME_UNIT_ALIASES: dict[str, str] = {
    "bbl": "bbl",
    "bbls": "bbl",
    "barrel": "bbl",
    "barrels": "bbl",
    "l": "l",
    "ltr": "l",
    "ltrs": "l",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "kl": "kl",
    "kiloliter": "kl",
    "kiloliters": "kl",
    "kilolitre": "kl",
    "kilolitres": "kl",
    "m3": "kl",
    "cbm": "kl",
}


def normalize_dip_unit(value: str | None) -> str | None:
    """Fold an accepted depth-unit spelling onto ``cm``, ``mm`` or ``m``."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("³", "").replace(".", "")
    if not text:
        return None
    return _DIP_UNIT_ALIASES.get(text)


def normalize_volume_unit(value: str | None) -> str | None:
    """Fold an accepted volume-unit spelling onto ``l``, ``kl`` or ``bbl``."""
    if value is None:
        return None
    text = str(value).strip().lower().replace("³", "").replace(".", "")
    if not text:
        return None
    return _VOLUME_UNIT_ALIASES.get(text)


def normalize_measurement_basis(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"dip", "dips", "innage", "dip/ullage", "dip ullage"}:
        return "Dip"
    if text in {"ullage", "outage", "freeboard"}:
        return "Ullage"
    return None


def to_canonical_dip(value: float, unit: str) -> float:
    """Convert a depth reading into canonical centimetres."""
    factor = DIP_UNIT_FACTORS[unit]
    return float(value) * factor


def to_canonical_volume(value: float, unit: str) -> float:
    """Convert a volume reading into canonical barrels."""
    factor = VOLUME_UNIT_FACTORS[unit]
    return float(value) * factor


def from_canonical_dip(value: float, unit: str) -> float:
    """Express a canonical centimetre value in the requested unit."""
    factor = DIP_UNIT_FACTORS[unit]
    return float(value) / factor


def from_canonical_volume(value: float, unit: str) -> float:
    """Express a canonical barrel value in the requested unit."""
    factor = VOLUME_UNIT_FACTORS[unit]
    return float(value) / factor


def unit_reference() -> dict:
    """Unit catalog for the UI, including every conversion factor in force."""
    return {
        "canonical_dip_unit": CANONICAL_DIP_UNIT,
        "canonical_volume_unit": CANONICAL_VOLUME_UNIT,
        "measurement_bases": list(MEASUREMENT_BASES),
        "dip_units": [
            {
                "code": code,
                "label": DIP_UNIT_LABELS[code],
                "factor_to_canonical": DIP_UNIT_FACTORS[code],
                "example": f"1 {code} = {DIP_UNIT_FACTORS[code]:g} cm",
            }
            for code in DIP_UNITS
        ],
        "volume_units": [
            {
                "code": code,
                "label": VOLUME_UNIT_LABELS[code],
                "factor_to_canonical": VOLUME_UNIT_FACTORS[code],
                "example": f"1 {code} = {VOLUME_UNIT_FACTORS[code]:.9g} bbl",
            }
            for code in VOLUME_UNITS
        ],
        "constants": {
            "liters_per_barrel": LITERS_PER_BARREL,
            "cubic_meters_per_barrel": CUBIC_METERS_PER_BARREL,
            "millimeters_per_centimeter": MILLIMETERS_PER_CENTIMETER,
            "centimeters_per_meter": CENTIMETERS_PER_METER,
            "liters_per_kiloliter": LITERS_PER_KILOLITER,
        },
    }
