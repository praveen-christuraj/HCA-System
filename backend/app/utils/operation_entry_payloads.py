"""Fixed Operation Entry payloads (owner decision, 2026-10-17).

OTMS lets an installation design its own Operation Template — fields, layout
sections and placements — and the Operation Entry page rendered whatever the
template master produced. The owner has ruled that this customisation is **not
needed** in HCA System: the payload for each module is fixed in code and used
directly by the Operation Entry page, the same way asset types (ADR-014) and
operation types (ADR-019) are closed catalogues.

One Operation Entry page covers every operation type and asset type. Each of
the six operation types maps to exactly one asset type (ADR-019) and therefore
to exactly one entry payload:

=======================  =================  =========================  =====================
Operation type           Asset type         Entry layout               Payload field code
=======================  =================  =========================  =====================
TANK_OPERATIONS          STORAGE_TANK       Tank Gauging               tank_gauging_payload
BARGE_OPERATIONS         BARGE              Multi-Tank Before/After    multi_tank_payload
SHUTTLE_OPERATIONS       SHUTTLE_VESSEL     Shuttle Tracking           shuttle_payload
FSO_OPERATIONS           FSO                FSO Tracking               fso_payload
TANKER_OPERATIONS        TANKER_TRAILER     Tanker Loading             tanker_payload
FLOWMETER_OPERATIONS     FLOWMETER          Meter Reading              flowmeter_payload
=======================  =================  =========================  =====================

The payload *shapes* are the OTMS payload shapes (``layout_type`` /
``calculation_engine`` / ``meta`` / ``inputs`` / ``calculated`` and the field
names inside them), so nothing downstream that reads an OTMS payload has to be
relearned. Persistence is typed columns and child tables (rule 4); the nested
objects exist only as transport.

This module imports nothing from the application so the seed script and tests
can use it too.
"""

from __future__ import annotations

from app.utils.operation_types import (
    BARGE_OPERATIONS,
    FLOWMETER_OPERATIONS,
    FSO_OPERATIONS,
    SHUTTLE_OPERATIONS,
    TANK_OPERATIONS,
    TANKER_OPERATIONS,
    get_operation_type,
)

# ---------------------------------------------------------------------------
# Payload schemas (fixed, versioned, never user-designed)
# ---------------------------------------------------------------------------
TANK_GAUGING_PAYLOAD = "tank_gauging_payload"
MULTI_TANK_PAYLOAD = "multi_tank_payload"
SHUTTLE_PAYLOAD = "shuttle_payload"
FSO_PAYLOAD = "fso_payload"
TANKER_PAYLOAD = "tanker_payload"
FLOWMETER_PAYLOAD = "flowmeter_payload"

LAYOUT_TANK_GAUGING = "Tank Gauging"
LAYOUT_MULTI_TANK = "Multi-Tank Before/After"
LAYOUT_SHUTTLE = "Shuttle Tracking"
LAYOUT_FSO = "FSO Tracking"
LAYOUT_TANKER = "Tanker Loading"
LAYOUT_FLOWMETER = "Meter Reading"

ENGINE_TANK_QUANTITY = "Tank Quantity"
ENGINE_BARGE_BEFORE_AFTER = "Barge Before/After Quantity"
ENGINE_TANKER_QUANTITY = "Tanker Quantity"
ENGINE_METER_READING = "Meter Reading Quantity"
ENGINE_SHUTTLE_NET = "Shuttle Net Movement"
ENGINE_FSO_NET = "FSO Net / Variance"

# OTMS payload schema tags carried inside shuttle / fso / flowmeter payloads.
SCHEMA_SHUTTLE_V2 = "shuttle_payload_v2"
SCHEMA_FSO_V2 = "fso_payload_v2"
SCHEMA_FLOWMETER_V2 = "flowmeter_payload_v2"

# ---------------------------------------------------------------------------
# Shared measurement limits (mirrors OTMS tankQuantityEngine constants)
# ---------------------------------------------------------------------------
WATER_DENSITY_AT_60F = 999.012
BARREL_TO_CUBIC_METER = 0.158987294928
LONG_TON_TO_METRIC_TON = 1.01605

TANK_TEMP_LIMITS = {"C": {"min": 15, "max": 70}, "F": {"min": 60, "max": 160}}
SAMPLE_TEMP_LIMITS = {"C": {"min": 15, "max": 70}, "F": {"min": 60, "max": 160}}
OBSERVED_API_LIMITS = {"min": 15.0, "max": 90.0}
OBSERVED_DENSITY_LIMITS = {"min": 600.0, "max": 1000.0}
BSW_LIMITS = {"min": 0.0, "max": 100.0}

OBSERVED_API = "Observed API"
OBSERVED_DENSITY = "Observed Density"

# Compartment / manhole options offered on the tanker layout (OTMS default C1).
TANKER_COMPARTMENTS = ("C1", "C2", "C3", "C4", "M1", "M2")

# Temporary seal keys of the multi-tank payload (OTMS ``buildDefaultAfterTemporarySeals``).
MULTI_TANK_TEMPORARY_SEAL_KEYS = (
    "portManifoldSeal",
    "stbdManifoldSeal",
    "pumproomSeal",
    "otherSeal",
    "otherRemarks",
)

# Permanent tank seal positions of the multi-tank payload.
MULTI_TANK_TANK_SEAL_POSITIONS = ("MH1", "MH2", "LOCK", "DIPHATCH")

# ---------------------------------------------------------------------------
# Entry definitions
# ---------------------------------------------------------------------------
OPERATION_ENTRY_DEFINITIONS: tuple[dict, ...] = (
    {
        "operation_type_code": TANK_OPERATIONS,
        "payload_field_code": TANK_GAUGING_PAYLOAD,
        "entry_layout_type": LAYOUT_TANK_GAUGING,
        "calculation_engine": ENGINE_TANK_QUANTITY,
        "payload_schema": "tank_gauging_payload_v1",
        "requires_convoy_number": False,
        "convoy_label": "Convoy Number",
        "supports_calibration": True,
        "supports_tank_operation": True,
        "summary": (
            "Manual tank dipping: dip, water level, temperatures, observed "
            "API/density, sample temperature and BS&W. Quantities are calculated "
            "from the asset's active calibration chart."
        ),
    },
    {
        "operation_type_code": BARGE_OPERATIONS,
        "payload_field_code": MULTI_TANK_PAYLOAD,
        "entry_layout_type": LAYOUT_MULTI_TANK,
        "calculation_engine": ENGINE_BARGE_BEFORE_AFTER,
        "payload_schema": "multi_tank_payload_v1",
        "requires_convoy_number": True,
        "convoy_label": "Convoy Number",
        "supports_calibration": True,
        "supports_tank_operation": False,
        "summary": (
            "Barge / YADE before-and-after gauging across every declared "
            "compartment, with per-tank dips, stage totals, net movement and "
            "seal capture."
        ),
    },
    {
        "operation_type_code": SHUTTLE_OPERATIONS,
        "payload_field_code": SHUTTLE_PAYLOAD,
        "entry_layout_type": LAYOUT_SHUTTLE,
        "calculation_engine": ENGINE_SHUTTLE_NET,
        "payload_schema": SCHEMA_SHUTTLE_V2,
        "requires_convoy_number": True,
        "convoy_label": "Shuttle Number",
        "supports_calibration": False,
        "supports_tank_operation": True,
        "summary": (
            "Shuttle voyage event: vessel operation, event time, opening and "
            "closing stock and water, with live net movement."
        ),
    },
    {
        "operation_type_code": FSO_OPERATIONS,
        "payload_field_code": FSO_PAYLOAD,
        "entry_layout_type": LAYOUT_FSO,
        "calculation_engine": ENGINE_FSO_NET,
        "payload_schema": SCHEMA_FSO_V2,
        "requires_convoy_number": False,
        "convoy_label": "Convoy Number",
        "supports_calibration": False,
        "supports_tank_operation": True,
        "summary": (
            "FSO event: operation, linked shuttle number, vessel name and "
            "quantity, opening and closing stock and water, with live net and "
            "variance against the vessel quantity."
        ),
    },
    {
        "operation_type_code": TANKER_OPERATIONS,
        "payload_field_code": TANKER_PAYLOAD,
        "entry_layout_type": LAYOUT_TANKER,
        "calculation_engine": ENGINE_TANKER_QUANTITY,
        "payload_schema": "tanker_payload_v1",
        "requires_convoy_number": True,
        "convoy_label": "Convoy Number",
        "supports_calibration": True,
        "supports_tank_operation": True,
        "summary": (
            "Tanker truck loading or receipt: compartment dips, sample "
            "parameters and C1/C2/M1/M2 seals. The prime mover and trailer "
            "come from the active Prime Mover-Tanker Link."
        ),
    },
    {
        "operation_type_code": FLOWMETER_OPERATIONS,
        "payload_field_code": FLOWMETER_PAYLOAD,
        "entry_layout_type": LAYOUT_FLOWMETER,
        "calculation_engine": ENGINE_METER_READING,
        "payload_schema": SCHEMA_FLOWMETER_V2,
        "requires_convoy_number": False,
        "convoy_label": "Convoy Number",
        "supports_calibration": False,
        "supports_tank_operation": False,
        "summary": (
            "Flowmeter stream readings: opening and closing readings per "
            "meter, stream gross observed volume, and the standard quality "
            "chain to net standard volume."
        ),
    },
)

_DEFINITIONS_BY_TYPE = {
    item["operation_type_code"]: item for item in OPERATION_ENTRY_DEFINITIONS
}

PAYLOAD_FIELD_CODES: tuple[str, ...] = tuple(
    item["payload_field_code"] for item in OPERATION_ENTRY_DEFINITIONS
)


def _fold(value) -> str:
    return "".join(ch for ch in str(value or "").strip().casefold() if ch.isalnum())


_TYPE_LOOKUP: dict[str, str] = {}
for _definition in OPERATION_ENTRY_DEFINITIONS:
    _TYPE_LOOKUP[_fold(_definition["operation_type_code"])] = _definition[
        "operation_type_code"
    ]


def get_entry_definition(operation_type_code: str | None) -> dict | None:
    """Return the fixed entry definition of an operation type, if any."""
    if not operation_type_code:
        return None
    code = _TYPE_LOOKUP.get(_fold(operation_type_code), str(operation_type_code).strip().upper())
    definition = _DEFINITIONS_BY_TYPE.get(code)
    return dict(definition) if definition else None


def entry_definition_catalog() -> list[dict]:
    """Full catalogue enriched with operation/asset type display names."""
    catalog = []
    for definition in OPERATION_ENTRY_DEFINITIONS:
        operation_type = get_operation_type(definition["operation_type_code"]) or {}
        catalog.append(
            {
                **definition,
                "operation_type_name": operation_type.get(
                    "name", definition["operation_type_code"]
                ),
                "asset_type_code": operation_type.get("asset_type_code"),
                "asset_type_name": operation_type.get("asset_type_name"),
            }
        )
    return catalog

# OTMS also ships two scalar-field layouts. Keep them as fixed alternatives,
# not user-designed templates. No arbitrary Standard Form fields are accepted.
MANUAL_LAYOUTS = {
    "vessel_cycle": {"payload_field_code": "vessel_cycle", "entry_layout_type": "Vessel Cycle",
        "calculation_engine": "Vessel Cycle Quantity", "operation_type_code": SHUTTLE_OPERATIONS,
        "fields": ["vessel_operation_code", "movement_reference", "counterparty_asset_code", "quantity_bbl", "water_bbl", "nsv_bbl"]},
    "stock_movement": {"payload_field_code": "stock_movement", "entry_layout_type": "Stock Movement",
        "calculation_engine": "Stock Movement Net/Variance", "operation_type_code": FSO_OPERATIONS,
        "fields": ["vessel_operation_code", "movement_reference", "opening_stock", "opening_water", "closing_stock", "closing_water", "net_stock", "net_water", "net_nsv"]},
}


def resolve_entry_definition(operation_type_code, payload_code=None):
    default = get_entry_definition(operation_type_code)
    if not default:
        raise ValueError("Unknown operation type")
    if not payload_code or payload_code == default["payload_field_code"]:
        return default
    variant = MANUAL_LAYOUTS.get(payload_code)
    if variant and variant["operation_type_code"] == operation_type_code:
        return {**default, **variant, "requires_convoy_number": False}
    raise ValueError("This fixed entry layout is not applicable to the operation type")
