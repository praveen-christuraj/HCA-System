"""Hard-coded asset type catalog.

Owner decision (2026-10-17): asset types are **hard coded**, not soft coded.

OTMS kept asset types in an editable ``asset_types`` master table. That let an
installation rename, add or delete types at runtime, which broke every
downstream rule that reasoned about an asset's nature -- the OTMS tracking code
ended up guessing a barge from the literal text ``barge`` inside a free-text
type code, and silently lost tickets for installations that called their barge
class ``YADE`` (see OTMS ``app/services/asset_family.py``).

HCA therefore ships a closed catalog of the seven hydrocarbon asset classes.
The catalog is the single source of truth for:

* the asset type dropdown and its validation,
* whether an asset of that type carries tanks,
* whether calibration applies to that type,
* the default dip/volume units offered for that type.

Adding a type is a code change with a review, never a runtime setting. This
module deliberately imports nothing from the application so the seed script and
tests can use it too.
"""

from __future__ import annotations

STORAGE_TANK = "STORAGE_TANK"
BARGE = "BARGE"
SHUTTLE_VESSEL = "SHUTTLE_VESSEL"
FSO = "FSO"
PRIME_MOVER = "PRIME_MOVER"
TANKER_TRAILER = "TANKER_TRAILER"
FLOWMETER = "FLOWMETER"

ASSET_TYPE_DEFINITIONS: tuple[dict, ...] = (
    {
        "code": STORAGE_TANK,
        "name": "Storage Tank",
        "description": "Fixed shore or terminal storage tank with a strapping table.",
        "supports_tanks": True,
        "multi_tank": False,
        "calibration_supported": True,
        "aliases": ("STORAGE TANK", "STORAGE_TANK", "STORAGE-TANK", "TANK"),
    },
    {
        "code": BARGE,
        "name": "Barge",
        "description": "Inland or coastal barge with multiple compartments.",
        "supports_tanks": True,
        "multi_tank": True,
        "calibration_supported": True,
        "aliases": ("BARGE", "BARGES", "YADE"),
    },
    {
        "code": SHUTTLE_VESSEL,
        "name": "Shuttle Vessel",
        "description": "Shuttle vessel moving cargo between offshore assets.",
        "supports_tanks": True,
        "multi_tank": True,
        "calibration_supported": True,
        "aliases": ("SHUTTLE VESSEL", "SHUTTLE_VESSEL", "SHUTTLE-VESSEL", "SHUTTLE"),
    },
    {
        "code": FSO,
        "name": "FSO",
        "description": "Floating storage offloading unit with cargo tanks.",
        "supports_tanks": True,
        "multi_tank": True,
        "calibration_supported": True,
        "aliases": ("FSO", "FPSO", "FLOATING STORAGE"),
    },
    {
        "code": PRIME_MOVER,
        "name": "Prime Mover",
        "description": "Truck tractor that hauls a tanker trailer. Carries no product tank.",
        "supports_tanks": False,
        "multi_tank": False,
        "calibration_supported": False,
        "aliases": ("PRIME MOVER", "PRIME_MOVER", "PRIME-MOVER", "PRIMEMOVER", "TRACTOR"),
    },
    {
        "code": TANKER_TRAILER,
        "name": "Tanker Trailer",
        "description": "Road tanker trailer; compartments are registered as tanks.",
        "supports_tanks": True,
        "multi_tank": True,
        "calibration_supported": True,
        "aliases": ("TANKER TRAILER", "TANKER_TRAILER", "TANKER-TRAILER", "TANKER", "TRAILER"),
    },
    {
        "code": FLOWMETER,
        "name": "Flowmeter",
        "description": "Custody-transfer meter proving a flow path. Has no tank to calibrate.",
        "supports_tanks": False,
        "multi_tank": False,
        "calibration_supported": False,
        "aliases": ("FLOWMETER", "FLOW METER", "FLOW_METER", "METER"),
    },
)

ASSET_TYPES: tuple[dict, ...] = ASSET_TYPE_DEFINITIONS
ASSET_TYPE_CODES: tuple[str, ...] = tuple(item["code"] for item in ASSET_TYPE_DEFINITIONS)

_ASSET_TYPES_BY_CODE = {item["code"]: item for item in ASSET_TYPE_DEFINITIONS}

# Import files and legacy OTMS data spell the same type many ways ("Storage
# Tank", "storage-tank", "PRIME MOVER"). Every alias folds onto one code so an
# import never has to guess.
_LOOKUP_BY_ALIAS: dict[str, str] = {}
for _definition in ASSET_TYPE_DEFINITIONS:
    _keys = set(_definition["aliases"])
    _keys.add(_definition["code"])
    _keys.add(_definition["name"])
    for _key in _keys:
        _LOOKUP_BY_ALIAS[_key.strip().casefold()] = _definition["code"]
        _LOOKUP_BY_ALIAS[_key.replace(" ", "_").casefold()] = _definition["code"]
        _LOOKUP_BY_ALIAS[_key.replace(" ", "-").casefold()] = _definition["code"]


def resolve_asset_type_code(value: str | None) -> str | None:
    """Fold any accepted spelling of an asset type onto its catalog code."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _LOOKUP_BY_ALIAS.get(text.casefold())


def is_valid_asset_type_code(value: str | None) -> bool:
    return str(value or "").strip() in _ASSET_TYPES_BY_CODE


def get_asset_type(code: str | None) -> dict | None:
    return _ASSET_TYPES_BY_CODE.get(str(code or "").strip())


def asset_type_supports_tanks(code: str | None) -> bool:
    definition = get_asset_type(code)
    return bool(definition and definition["supports_tanks"])


def asset_type_supports_calibration(code: str | None) -> bool:
    definition = get_asset_type(code)
    return bool(definition and definition["calibration_supported"])


def asset_type_names() -> tuple[str, ...]:
    return tuple(item["name"] for item in ASSET_TYPE_DEFINITIONS)


def asset_type_catalog() -> list[dict]:
    """Catalog shaped for the API and the asset form dropdown."""
    return [
        {
            "code": item["code"],
            "name": item["name"],
            "description": item["description"],
            "supports_tanks": item["supports_tanks"],
            "multi_tank": item["multi_tank"],
            "calibration_supported": item["calibration_supported"],
            "aliases": list(item["aliases"]),
        }
        for item in ASSET_TYPE_DEFINITIONS
    ]
