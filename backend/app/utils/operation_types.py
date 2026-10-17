"""Hard-coded operation types, operation categories and stock signs.

Owner decision (2026-10-17, Configurations module): operation types and their
categories are **hard coded**, not soft coded. OTMS kept operation types in an
editable ``operation_types`` table, so an installation could rename or delete a
type that the stock logic depended on. HCA ships the closed catalogue below and
the Operation Master can only reference these codes.

* Each operation type is bound to exactly one asset type from
  ``app.utils.asset_types``. A Prime Mover carries no operation of its own: it
  connects to a Tanker Trailer, and the tanker's operations are the ones that
  are recorded.
* Each category carries one stock sign. The sign decides how an operation
  changes the stock balance:

  - ``SET``     overrides the stock balance with the measured quantity,
  - ``IN``      adds to the stock balance,
  - ``OUT``     subtracts from the stock balance,
  - ``NEUTRAL`` is accounted in the register but does not override the stock.

This module imports nothing from the application so the seed script and tests
can use it too.
"""

from __future__ import annotations

from app.utils.asset_types import (
    BARGE,
    FLOWMETER,
    FSO,
    SHUTTLE_VESSEL,
    STORAGE_TANK,
    TANKER_TRAILER,
    get_asset_type,
)

# ---------------------------------------------------------------------------
# Stock signs
# ---------------------------------------------------------------------------
SIGN_SET = "SET"
SIGN_IN = "IN"
SIGN_OUT = "OUT"
SIGN_NEUTRAL = "NEUTRAL"

OPERATION_SIGNS: tuple[dict, ...] = (
    {
        "code": SIGN_SET,
        "label": "Set",
        "meaning": "Overrides the stock balance with the measured quantity.",
    },
    {
        "code": SIGN_IN,
        "label": "In",
        "meaning": "Adds the quantity to the stock balance.",
    },
    {
        "code": SIGN_OUT,
        "label": "Out",
        "meaning": "Subtracts the quantity from the stock balance.",
    },
    {
        "code": SIGN_NEUTRAL,
        "label": "Neutral",
        "meaning": (
            "Accounted in the operation register, but does not override or change the stock balance."
        ),
    },
)
OPERATION_SIGN_CODES: tuple[str, ...] = tuple(item["code"] for item in OPERATION_SIGNS)

# ---------------------------------------------------------------------------
# Operation categories (fixed list, with their stock sign)
# ---------------------------------------------------------------------------
OPENING_STOCK = "OPENING_STOCK"
RECEIPT = "RECEIPT"
DISPATCH = "DISPATCH"
EXPORT = "EXPORT"
CLOSING_STOCK = "CLOSING_STOCK"
DRAINING = "DRAINING"
DECANTING = "DECANTING"
ITT = "ITT"

OPERATION_CATEGORIES: tuple[dict, ...] = (
    {
        "code": OPENING_STOCK,
        "label": "OPENING STOCK",
        "sign": SIGN_SET,
        "description": "Stock position at the start of an accounting period.",
    },
    {
        "code": RECEIPT,
        "label": "RECEIPT",
        "sign": SIGN_IN,
        "description": "Product received into the location.",
    },
    {
        "code": DISPATCH,
        "label": "DISPATCH",
        "sign": SIGN_OUT,
        "description": "Product dispatched out of the location.",
    },
    {
        "code": EXPORT,
        "label": "EXPORT",
        "sign": SIGN_OUT,
        "description": "Product exported out of the location.",
    },
    {
        "code": CLOSING_STOCK,
        "label": "CLOSING STOCK",
        "sign": SIGN_SET,
        "description": "Stock position at the end of an accounting period.",
    },
    {
        "code": DRAINING,
        "label": "DRAINING",
        "sign": SIGN_OUT,
        "description": "Product drained from a tank, vessel or trailer.",
    },
    {
        "code": DECANTING,
        "label": "DECANTING",
        "sign": SIGN_OUT,
        "description": "Product decanted (separated off) from the stock.",
    },
    {
        "code": ITT,
        "label": "ITT",
        "sign": SIGN_NEUTRAL,
        "description": "Inter-tank transfer. Accounted, but does not change total stock.",
    },
)
OPERATION_CATEGORY_CODES: tuple[str, ...] = tuple(item["code"] for item in OPERATION_CATEGORIES)

_CATEGORIES_BY_CODE = {item["code"]: item for item in OPERATION_CATEGORIES}

# ---------------------------------------------------------------------------
# Operation types (fixed list, each bound to one asset type)
# ---------------------------------------------------------------------------
TANK_OPERATIONS = "TANK_OPERATIONS"
BARGE_OPERATIONS = "BARGE_OPERATIONS"
SHUTTLE_OPERATIONS = "SHUTTLE_OPERATIONS"
FSO_OPERATIONS = "FSO_OPERATIONS"
TANKER_OPERATIONS = "TANKER_OPERATIONS"
FLOWMETER_OPERATIONS = "FLOWMETER_OPERATIONS"

OPERATION_TYPE_DEFINITIONS: tuple[dict, ...] = (
    {
        "code": TANK_OPERATIONS,
        "name": "Tank Operations",
        "asset_type_code": STORAGE_TANK,
        "description": "Operations recorded against a fixed storage tank.",
    },
    {
        "code": BARGE_OPERATIONS,
        "name": "Barge Operations",
        "asset_type_code": BARGE,
        "description": "Operations recorded against a barge and its compartments.",
    },
    {
        "code": SHUTTLE_OPERATIONS,
        "name": "Shuttle Operations",
        "asset_type_code": SHUTTLE_VESSEL,
        "description": "Operations recorded against a shuttle vessel.",
    },
    {
        "code": FSO_OPERATIONS,
        "name": "FSO Operations",
        "asset_type_code": FSO,
        "description": "Operations recorded against an FSO unit.",
    },
    {
        "code": TANKER_OPERATIONS,
        "name": "Tanker Operations",
        "asset_type_code": TANKER_TRAILER,
        "description": (
            "Operations recorded against a tanker trailer. Prime Movers connect to tanker "
            "trailers through the Prime Mover-Tanker Link but carry no operation of their own."
        ),
    },
    {
        "code": FLOWMETER_OPERATIONS,
        "name": "Flowmeter Operations",
        "asset_type_code": FLOWMETER,
        "description": "Operations recorded against a custody-transfer flowmeter.",
    },
)
OPERATION_TYPE_CODES: tuple[str, ...] = tuple(item["code"] for item in OPERATION_TYPE_DEFINITIONS)

_TYPES_BY_CODE = {item["code"]: item for item in OPERATION_TYPE_DEFINITIONS}


def _fold(value) -> str:
    """Case-, space-, hyphen- and underscore-insensitive lookup key."""
    return "".join(ch for ch in str(value or "").strip().casefold() if ch.isalnum())


_TYPE_LOOKUP: dict[str, str] = {}
for _definition in OPERATION_TYPE_DEFINITIONS:
    _TYPE_LOOKUP[_fold(_definition["code"])] = _definition["code"]
    _TYPE_LOOKUP[_fold(_definition["name"])] = _definition["code"]

_CATEGORY_LOOKUP: dict[str, str] = {}
for _definition in OPERATION_CATEGORIES:
    _CATEGORY_LOOKUP[_fold(_definition["code"])] = _definition["code"]
    _CATEGORY_LOOKUP[_fold(_definition["label"])] = _definition["code"]


def resolve_operation_type_code(value: str | None) -> str | None:
    """Fold any accepted spelling of an operation type onto its catalog code."""
    if value is None:
        return None
    return _TYPE_LOOKUP.get(_fold(value))


def resolve_operation_category_code(value: str | None) -> str | None:
    """Fold any accepted spelling of a category onto its catalog code."""
    if value is None:
        return None
    return _CATEGORY_LOOKUP.get(_fold(value))


def get_operation_type(code: str | None) -> dict | None:
    if not code:
        return None
    definition = _TYPES_BY_CODE.get(str(code).strip().upper())
    if definition is None:
        return None
    asset_type = get_asset_type(definition["asset_type_code"]) or {}
    return {
        **definition,
        "asset_type_name": asset_type.get("name", definition["asset_type_code"]),
    }


def get_operation_category(code: str | None) -> dict | None:
    if not code:
        return None
    definition = _CATEGORIES_BY_CODE.get(str(code).strip().upper())
    return dict(definition) if definition else None


def sign_for_category(category_code: str) -> str:
    """Stock sign of a category. Raises KeyError for an unknown category."""
    return _CATEGORIES_BY_CODE[category_code]["sign"]


def operation_type_catalog() -> list[dict]:
    return [get_operation_type(item["code"]) for item in OPERATION_TYPE_DEFINITIONS]


def operation_category_catalog() -> list[dict]:
    return [dict(item) for item in OPERATION_CATEGORIES]


def operation_sign_catalog() -> list[dict]:
    return [dict(item) for item in OPERATION_SIGNS]
