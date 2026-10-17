"""Asset Master — hard-coded asset types, tanks, scope and calibration.

Combines what OTMS kept in three separate masters (asset type, asset,
calibration template) behind one API. The differences that matter:

* **Asset types are hard coded** (``app.utils.asset_types``). There is no
  ``asset_types`` table to edit, so an asset's nature can never drift away from
  the rules that depend on it.
* **Tanks are declared with the asset.** A barge or FSO carries several, and the
  calibration chart is keyed by these exact names.
* **Calibration charts have a fixed three-column shape** — tank name,
  dip/ullage, volume — instead of OTMS's user-designed template columns stored
  as ``row_data`` JSONB.
* **Everything is stored in canonical cm and bbl**, with the supplied values
  kept alongside so a conversion can always be re-checked.
"""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import get_user_location_ids, require_permission
from app.models import (
    Asset,
    AssetCalibrationRow,
    AssetCalibrationTable,
    AssetTank,
    Location,
    User,
)
from app.schemas import (
    AssetCreate,
    AssetUpdate,
    VolumeLookupBatchRequest,
    VolumeLookupRequest,
)
from app.services.audit_service import create_audit_log
from app.services.calibration_engine import (
    CalibrationError,
    CalibrationPoint,
    curve_summary,
    interpolate_3d,
    validate_curve_monotonic,
)
from app.services.calibration_import import parse_calibration_chart
from app.services.serializers import (
    asset_to_dict,
    calibration_row_to_dict,
    calibration_table_to_dict,
)
from app.utils.asset_types import (
    asset_type_catalog,
    asset_type_supports_calibration,
    asset_type_supports_tanks,
    get_asset_type,
    resolve_asset_type_code,
)
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import clean_optional_text
from app.utils.pagination import paginate_query
from app.utils.time import utcnow
from app.utils.units import (
    CANONICAL_DIP_UNIT,
    CANONICAL_VOLUME_UNIT,
    DIP_UNITS,
    MEASUREMENT_BASES,
    VOLUME_UNITS,
    from_canonical_dip,
    from_canonical_volume,
    normalize_dip_unit,
    normalize_measurement_basis,
    normalize_volume_unit,
    to_canonical_dip,
    unit_reference,
)

router = APIRouter(prefix="/assets", tags=["Asset Master"])

MODULE_NAME = "Asset Master"
CALIBRATION_MODULE_NAME = "Asset Calibration"

CHART_TEMPLATE_HEADERS = ["tank_name", "dip_ullage", "volume"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _normalise_code(value: str) -> str:
    return value.strip().upper()


def _scoped_assets(db: Session, user: User):
    """Assets the user may see: global assets plus their assigned locations."""
    query = db.query(Asset)
    allowed = get_user_location_ids(db, user)
    if allowed is None:
        return query
    if not allowed:
        return query.filter(Asset.asset_scope == "Global")
    return query.filter(or_(Asset.asset_scope == "Global", Asset.location_id.in_(allowed)))


def _get_asset(db: Session, user: User, asset_id: int) -> Asset:
    asset = (
        _scoped_assets(db, user)
        .options(
            joinedload(Asset.location),
            selectinload(Asset.tanks),
            joinedload(Asset.calibration_table).selectinload(AssetCalibrationTable.rows),
        )
        .filter(Asset.id == asset_id)
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _filtered_assets(
    db: Session,
    user: User,
    *,
    search: str | None,
    status: str | None,
    asset_type_code: str | None,
    asset_scope: str | None,
    location_id: int | None,
    calibration_required: bool | None,
    has_calibration: bool | None,
    date_from: date | None,
    date_to: date | None,
):
    query = _scoped_assets(db, user).options(
        joinedload(Asset.location),
        selectinload(Asset.tanks),
        joinedload(Asset.calibration_table),
    )
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Asset.asset_name.ilike(term),
                Asset.asset_code.ilike(term),
                Asset.serial_number.ilike(term),
                Asset.manufacturer.ilike(term),
                Asset.description.ilike(term),
            )
        )
    if status:
        query = query.filter(Asset.status == status)
    if asset_type_code:
        resolved = resolve_asset_type_code(asset_type_code)
        query = query.filter(Asset.asset_type_code == (resolved or asset_type_code.strip().upper()))
    if asset_scope:
        query = query.filter(Asset.asset_scope == asset_scope)
    if location_id is not None:
        query = query.filter(Asset.location_id == location_id)
    if calibration_required is not None:
        query = query.filter(Asset.calibration_required == calibration_required)
    if has_calibration is not None:
        subquery = db.query(AssetCalibrationTable.asset_id).filter(
            AssetCalibrationTable.status == "Active"
        )
        query = query.filter(
            Asset.id.in_(subquery) if has_calibration else ~Asset.id.in_(subquery)
        )
    if date_from:
        query = query.filter(Asset.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Asset.created_at <= datetime.combine(date_to, time.max))
    return query


def _resolve_asset_type_or_422(raw_code: str) -> dict:
    resolved = resolve_asset_type_code(raw_code)
    if resolved is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown asset type '{raw_code}'. Asset types are fixed: "
                + ", ".join(item["name"] for item in asset_type_catalog())
            ),
        )
    return get_asset_type(resolved)


def _validate_tanks(payload_tanks: list, asset_type: dict) -> list[dict]:
    """Validate the declared tanks against the asset type's capability."""
    tanks = [
        {
            "tank_name": clean_optional_text(item.tank_name) or "",
            "tank_code": clean_optional_text(item.tank_code),
            "sort_order": item.sort_order,
            "description": clean_optional_text(item.description),
        }
        for item in payload_tanks
    ]
    tanks = [tank for tank in tanks if tank["tank_name"]]

    if tanks and not asset_type["supports_tanks"]:
        raise HTTPException(
            status_code=422,
            detail=f"An asset of type {asset_type['name']} does not carry tanks",
        )

    seen: set[str] = set()
    for index, tank in enumerate(tanks):
        key = tank["tank_name"].casefold()
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f"Tank name '{tank['tank_name']}' is declared twice on this asset",
            )
        seen.add(key)
        if tank["sort_order"] is None:
            tank["sort_order"] = index + 1
    return tanks


def _validate_calibration_flag(asset_type: dict, calibration_required: bool, tanks: list[dict]) -> None:
    if calibration_required and not asset_type["calibration_supported"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{asset_type['name']} assets are not calibrated. "
                "Turn off 'Calibration required' for this asset type."
            ),
        )
    if calibration_required and not tanks:
        raise HTTPException(
            status_code=422,
            detail="Declare at least one tank before marking this asset as requiring calibration",
        )


def _validate_scope(db: Session, scope: str, location_id: int | None) -> Location | None:
    """Local assets must sit on an active location; global assets must not."""
    if scope == "Global":
        return None
    if location_id is None:
        raise HTTPException(status_code=422, detail="A location is required for a Local asset")
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=422, detail="The selected location was not found")
    if location.status != "Active":
        raise HTTPException(
            status_code=422,
            detail="Only an Active location can hold a Local asset",
        )
    return location


def _ensure_location_scope(db: Session, user: User, location_id: int | None) -> None:
    allowed = get_user_location_ids(db, user)
    if allowed is None or location_id is None:
        return
    if location_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail="That location is not in your assigned scope",
        )


def _apply_tanks(asset: Asset, tanks: list[dict]) -> None:
    """Reconcile by tank identity; adding a compartment must not delete chart/seal FKs."""
    existing = {tank.tank_name.casefold(): tank for tank in asset.tanks}
    wanted = {tank["tank_name"].casefold() for tank in tanks}
    for key, tank in existing.items():
        if key not in wanted:
            asset.tanks.remove(tank)
    for values in tanks:
        tank = existing.get(values["tank_name"].casefold())
        if tank is None:
            tank = AssetTank()
            asset.tanks.append(tank)
        for field in ("tank_name", "tank_code", "sort_order", "description"):
            setattr(tank, field, values[field])


def _asset_summary(asset: Asset) -> str:
    return f"{asset.asset_name} ({asset.asset_code})"


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
@router.get("/reference")
def asset_reference(
    user: User = Depends(require_permission("assets:read")),
):
    """Hard-coded asset types plus the unit catalog and conversion factors."""
    return {
        "asset_types": asset_type_catalog(),
        "units": unit_reference(),
        "measurement_bases": list(MEASUREMENT_BASES),
        "dip_units": list(DIP_UNITS),
        "volume_units": list(VOLUME_UNITS),
        "canonical_dip_unit": CANONICAL_DIP_UNIT,
        "canonical_volume_unit": CANONICAL_VOLUME_UNIT,
        "chart_template_headers": CHART_TEMPLATE_HEADERS,
        "scopes": ["Local", "Global"],
    }


# ---------------------------------------------------------------------------
# List, export, import
# ---------------------------------------------------------------------------
@router.get("")
def list_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    asset_type_code: str | None = None,
    asset_scope: str | None = None,
    location_id: int | None = None,
    calibration_required: bool | None = None,
    has_calibration: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_assets(
        db,
        user,
        search=search,
        status=status,
        asset_type_code=asset_type_code,
        asset_scope=asset_scope,
        location_id=location_id,
        calibration_required=calibration_required,
        has_calibration=has_calibration,
        date_from=date_from,
        date_to=date_to,
    ).order_by(Asset.asset_code.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [asset_to_dict(item) for item in result["items"]]
    result["asset_types"] = asset_type_catalog()
    return result


@router.get("/export")
def export_assets(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    asset_type_code: str | None = None,
    asset_scope: str | None = None,
    location_id: int | None = None,
    calibration_required: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_assets(
            db,
            actor,
            search=search,
            status=status,
            asset_type_code=asset_type_code,
            asset_scope=asset_scope,
            location_id=location_id,
            calibration_required=calibration_required,
            has_calibration=None,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(Asset.asset_code.asc())
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Asset code",
        "Asset name",
        "Asset type",
        "Scope",
        "Location",
        "Tanks",
        "Calibration required",
        "Dip unit",
        "Volume unit",
        "Serial number",
        "Manufacturer",
        "Model",
        "Commissioned",
        "Status",
        "Created",
    ]
    rows = []
    for asset in records:
        tanks = sorted(asset.tanks, key=lambda item: (item.sort_order or 0, item.tank_name))
        rows.append(
            [
                asset.asset_code,
                asset.asset_name,
                (get_asset_type(asset.asset_type_code) or {}).get("name", asset.asset_type_code),
                asset.asset_scope,
                (
                    f"{asset.location.location_name} ({asset.location.location_code})"
                    if asset.location
                    else "Global"
                ),
                "; ".join(tank.tank_name for tank in tanks),
                "Yes" if asset.calibration_required else "No",
                asset.dip_unit,
                asset.volume_unit,
                asset.serial_number or "",
                asset.manufacturer or "",
                asset.model or "",
                asset.commission_date or "",
                asset.status,
                asset.created_at,
            ]
        )
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"asset_type={asset_type_code}" if asset_type_code else "",
            f"scope={asset_scope}" if asset_scope else "",
            f"location_id={location_id}" if location_id is not None else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Export Assets",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Asset register exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response(
            "assets", "Asset Master", headers, rows,
            [16, 30, 18, 10, 30, 34, 20, 12, 14, 20, 22, 18, 16, 12, 22],
        )
    if format == "pdf":
        return pdf_response(
            "assets", "Asset Master", headers, rows,
            [22, 34, 22, 12, 32, 36, 20, 12, 14, 22, 24, 20, 18, 14, 24],
            filters_summary=filters_summary,
        )
    return csv_response("assets", headers, rows)


@router.post("/import")
def import_assets(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("assets:create")),
    db: Session = Depends(get_db),
):
    """Preview then commit an asset register.

    Columns: ``asset_code, asset_name, asset_type, asset_scope, location_code,
    tank_names, calibration_required, dip_unit, volume_unit, serial_number,
    manufacturer, model, commission_date, description, status``. Tank names are
    semicolon-separated; asset type accepts any catalog spelling.
    """
    from app.services.master_import import read_master_import

    try:
        table = read_master_import(file.file.read(), file.filename or "")
    except ValueError as exc:
        preview = {
            "filename": file.filename or "",
            "format": "",
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "columns_detected": [],
            "missing_columns": [],
            "rows": [],
            "message": str(exc),
        }
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Asset Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Asset import preview failed for {file.filename or 'upload'}",
            details_summary=str(exc),
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    aliases = {
        "name": "asset_name",
        "code": "asset_code",
        "asset_type": "asset_type",
        "type": "asset_type",
        "scope": "asset_scope",
        "location": "location_code",
        "tanks": "tank_names",
        "tank": "tank_names",
        "calibration": "calibration_required",
    }
    rows_source = []
    for raw in table["rows"]:
        row = dict(raw)
        for alias, canonical in aliases.items():
            if canonical not in row and alias in row:
                row[canonical] = row[alias]
        rows_source.append(row)
    columns = set(table["columns"])
    for alias, canonical in aliases.items():
        if alias in columns:
            columns.add(canonical)
    required = {"asset_code", "asset_name", "asset_type"}
    missing = sorted(required - columns)

    existing_codes = {
        str(code).strip().casefold() for (code,) in db.query(Asset.asset_code).all()
    }
    locations_by_code = {
        str(code).strip().casefold(): location
        for code, location in db.query(Location.location_code, Location).all()
    }
    allowed_locations = get_user_location_ids(db, actor)

    prepared = []
    staged_codes: set[str] = set()
    for raw in rows_source:
        code = _normalise_code(raw.get("asset_code", ""))
        name = raw.get("asset_name", "").strip()
        raw_type = raw.get("asset_type", "").strip()
        scope = raw.get("asset_scope", "Local").strip() or "Local"
        location_code = _normalise_code(raw.get("location_code", "")) if raw.get("location_code") else ""
        calibration_text = (raw.get("calibration_required", "Yes").strip() or "Yes").lower()
        status = raw.get("status", "Active").strip() or "Active"
        dip_unit = normalize_dip_unit(raw.get("dip_unit", "cm")) or "cm"
        volume_unit = normalize_volume_unit(raw.get("volume_unit", "bbl")) or "bbl"
        tank_names = [
            part.strip()
            for part in raw.get("tank_names", "").replace(";", ",").split(",")
            if part.strip()
        ]

        errors = []
        if not code:
            errors.append("Asset code is required")
        elif len(code) > 80:
            errors.append("Asset code must be 80 characters or fewer")
        if not name:
            errors.append("Asset name is required")
        elif len(name) > 150:
            errors.append("Asset name must be 150 characters or fewer")
        if not raw_type:
            errors.append("Asset type is required")
        asset_type = _resolve_asset_type_code_quietly(raw_type)
        if raw_type and asset_type is None:
            errors.append(f"Unknown asset type '{raw_type}'")
        if scope.title() not in {"Local", "Global"}:
            errors.append("Asset scope must be Local or Global")
        scope = scope.title()
        if status not in {"Active", "Inactive"}:
            errors.append("Status must be Active or Inactive")
        if calibration_text in {"yes", "y", "true", "1"}:
            calibration_required = True
        elif calibration_text in {"no", "n", "false", "0", ""}:
            calibration_required = False
        else:
            calibration_required = True
            errors.append("Calibration required must be Yes or No")
        if code.casefold() in existing_codes:
            errors.append("Asset code already exists")
        if code and code.casefold() in staged_codes:
            errors.append("Duplicate asset code in file")
        if code:
            staged_codes.add(code.casefold())

        location = None
        if scope == "Local":
            if not location_code:
                errors.append("Location code is required for a Local asset")
            else:
                location = locations_by_code.get(location_code.casefold())
                if location is None:
                    errors.append(f"Location code not found: {location_code}")
                elif location.status != "Active":
                    errors.append(f"Location {location_code} is not Active")
                elif allowed_locations is not None and location.id not in allowed_locations:
                    errors.append(f"Location {location_code} is not in your assigned scope")
        elif location_code:
            errors.append("A Global asset must not have a location code")

        if asset_type is not None:
            if tank_names and not asset_type["supports_tanks"]:
                errors.append(f"{asset_type['name']} assets do not carry tanks")
            if calibration_required and not asset_type["calibration_supported"]:
                errors.append(f"{asset_type['name']} assets are not calibrated")
            if calibration_required and not tank_names:
                errors.append("Declare at least one tank for a calibrated asset")

        duplicate_tanks = {
            name.casefold() for name in tank_names if tank_names.count(name) > 1
        }
        if duplicate_tanks:
            errors.append("Duplicate tank names: " + ", ".join(sorted(duplicate_tanks)))

        prepared.append(
            {
                "row_number": raw["row_number"],
                "asset_code": code,
                "asset_name": name,
                "asset_type_code": asset_type["code"] if asset_type else raw_type,
                "asset_type_name": asset_type["name"] if asset_type else raw_type,
                "asset_scope": scope,
                "location_code": location_code,
                "location_id": location.id if location else None,
                "calibration_required": calibration_required,
                "dip_unit": dip_unit,
                "volume_unit": volume_unit,
                "tank_names": tank_names,
                "serial_number": raw.get("serial_number", "").strip(),
                "manufacturer": raw.get("manufacturer", "").strip(),
                "model": raw.get("model", "").strip(),
                "commission_date": raw.get("commission_date", "").strip(),
                "description": raw.get("description", "").strip(),
                "status": status,
                "errors": errors,
            }
        )

    preview_rows = [
        {
            "row_number": row["row_number"],
            "asset_code": row["asset_code"],
            "asset_name": row["asset_name"],
            "asset_type_name": row["asset_type_name"],
            "asset_scope": row["asset_scope"],
            "location_code": row["location_code"],
            "tank_names": "; ".join(row["tank_names"]),
            "calibration_required": "Yes" if row["calibration_required"] else "No",
            "status": row["status"],
            "valid": not row["errors"],
            "errors": row["errors"],
        }
        for row in prepared
    ]
    total = len(prepared)
    valid = sum(1 for row in preview_rows if row["valid"])
    preview = {
        "filename": table["filename"],
        "format": table["format"],
        "total_rows": total,
        "valid_rows": valid,
        "invalid_rows": total - valid,
        "columns_detected": table["columns"],
        "missing_columns": missing,
        "rows": preview_rows,
        "message": (
            "Missing required columns: " + ", ".join(missing)
            if missing
            else f"{valid} row(s) ready to import" if valid
            else "No valid rows to import"
        ),
    }
    if missing or total == 0:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Asset Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Asset import preview rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; missing={', '.join(missing) or 'none'}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Asset Import",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Asset import previewed from {table['filename']}",
            details_summary=(
                f"file={table['filename']}; rows={total}; valid={valid}; invalid={total - valid}"
            ),
        )
        db.commit()
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Import Assets",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Asset import rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; invalid={total - valid}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    try:
        for row in prepared:
            commission = _parse_import_date(row["commission_date"])
            asset = Asset(
                asset_name=row["asset_name"],
                asset_code=row["asset_code"],
                asset_type_code=row["asset_type_code"],
                asset_scope=row["asset_scope"],
                location_id=row["location_id"],
                calibration_required=row["calibration_required"],
                dip_unit=row["dip_unit"],
                volume_unit=row["volume_unit"],
                serial_number=row["serial_number"] or None,
                manufacturer=row["manufacturer"] or None,
                model=row["model"] or None,
                commission_date=commission,
                description=row["description"] or None,
                status=row["status"],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(asset)
            db.flush()
            for index, tank_name in enumerate(row["tank_names"], start=1):
                db.add(
                    AssetTank(
                        asset_id=asset.id,
                        tank_name=tank_name,
                        sort_order=index,
                    )
                )
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Import Assets",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Asset import committed from {table['filename']}",
            details_summary=f"file={table['filename']}; rows={total}; imported={valid}; invalid=0",
            status_code=201,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="One or more asset codes already exist")
    preview["imported"] = valid
    preview["message"] = f"{valid} asset(s) imported successfully"
    return preview


def _resolve_asset_type_code_quietly(raw: str) -> dict | None:
    resolved = resolve_asset_type_code(raw)
    return get_asset_type(resolved) if resolved else None


def _parse_import_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Create / read / update / deactivate
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_asset(
    payload: AssetCreate,
    request: Request,
    actor: User = Depends(require_permission("assets:create")),
    db: Session = Depends(get_db),
):
    code = _normalise_code(payload.asset_code)
    asset_type = _resolve_asset_type_or_422(payload.asset_type_code)
    tanks = _validate_tanks(payload.tanks, asset_type)
    _validate_calibration_flag(asset_type, payload.calibration_required, tanks)

    if db.query(Asset.id).filter(func.lower(func.trim(Asset.asset_code)) == code.casefold()).first():
        raise HTTPException(status_code=409, detail="Asset code already exists")

    location = _validate_scope(db, payload.asset_scope, payload.location_id)
    _ensure_location_scope(db, actor, payload.location_id)

    asset = Asset(
        asset_name=payload.asset_name.strip(),
        asset_code=code,
        asset_type_code=asset_type["code"],
        asset_scope=payload.asset_scope,
        location_id=location.id if location else None,
        calibration_required=payload.calibration_required,
        dip_unit=payload.dip_unit,
        volume_unit=payload.volume_unit,
        serial_number=clean_optional_text(payload.serial_number),
        manufacturer=clean_optional_text(payload.manufacturer),
        model=clean_optional_text(payload.model),
        commission_date=payload.commission_date,
        description=clean_optional_text(payload.description),
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(asset)
    db.flush()
    _apply_tanks(asset, tanks)
    db.flush()

    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Create Asset",
        current_user=actor,
        request=request,
        entity_type="Asset",
        entity_id=asset.id,
        entity_label=_asset_summary(asset),
        remarks=f"{asset_type['name']} asset created",
        details_summary=(
            f"type={asset_type['code']}; scope={asset.asset_scope}; "
            f"location={location.location_code if location else 'Global'}; "
            f"tanks={len(tanks)}; calibration={'Yes' if asset.calibration_required else 'No'}"
        ),
        new_status=asset.status,
        status_code=201,
    )
    db.commit()
    db.refresh(asset)
    return asset_to_dict(_get_asset(db, actor, asset.id))


@router.get("/{asset_id}")
def get_asset(
    asset_id: int,
    user: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    asset = _get_asset(db, user, asset_id)
    payload = asset_to_dict(asset)
    payload["calibration"] = calibration_table_to_dict(
        asset.calibration_table,
        include_rows=True,
        row_limit=2000,
    )
    return payload


@router.put("/{asset_id}")
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    request: Request,
    actor: User = Depends(require_permission("assets:update")),
    db: Session = Depends(get_db),
):
    asset = _get_asset(db, actor, asset_id)
    changes: list[str] = []

    if payload.asset_name is not None and payload.asset_name.strip() != asset.asset_name:
        changes.append(f"name: {asset.asset_name} -> {payload.asset_name.strip()}")
        asset.asset_name = payload.asset_name.strip()

    if payload.asset_code is not None:
        code = _normalise_code(payload.asset_code)
        if code != asset.asset_code:
            duplicate = (
                db.query(Asset.id)
                .filter(
                    func.lower(func.trim(Asset.asset_code)) == code.casefold(),
                    Asset.id != asset.id,
                )
                .first()
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="Asset code already exists")
            changes.append(f"code: {asset.asset_code} -> {code}")
            asset.asset_code = code

    asset_type = get_asset_type(asset.asset_type_code)
    if payload.asset_type_code is not None:
        asset_type = _resolve_asset_type_or_422(payload.asset_type_code)
        if asset_type["code"] != asset.asset_type_code:
            changes.append(f"type: {asset.asset_type_code} -> {asset_type['code']}")
            asset.asset_type_code = asset_type["code"]

    scope = payload.asset_scope or asset.asset_scope
    location_id = payload.location_id if payload.location_id is not None else asset.location_id
    if payload.location_id is None and payload.asset_scope == "Global":
        location_id = None
    location = _validate_scope(db, scope, location_id)
    if scope != asset.asset_scope:
        changes.append(f"scope: {asset.asset_scope} -> {scope}")
        asset.asset_scope = scope
    resolved_location_id = location.id if location else None
    if resolved_location_id != asset.location_id:
        _ensure_location_scope(db, actor, resolved_location_id)
        changes.append(
            f"location: {asset.location.location_code if asset.location else 'Global'} -> "
            f"{location.location_code if location else 'Global'}"
        )
        asset.location_id = resolved_location_id

    tanks_payload = payload.tanks
    tank_count = len(asset.tanks)
    if tanks_payload is not None:
        tanks = _validate_tanks(tanks_payload, asset_type)
        existing_names = {tank.tank_name.casefold() for tank in asset.tanks}
        new_names = {tank["tank_name"].casefold() for tank in tanks}
        removed = existing_names - new_names
        if removed:
            from app.models import BargeSealMaster
            referenced = {seal.tank_id for seal in db.query(BargeSealMaster).filter_by(asset_id=asset.id)}
            lost_seals = [tank.tank_name for tank in asset.tanks if tank.id in referenced and tank.tank_name.casefold() in removed]
            if lost_seals:
                raise HTTPException(422, "Tank(s) " + ", ".join(lost_seals) + " are referenced by Barge Seal Master. Reassign those references before removing tanks.")
        if removed and asset.calibration_table:
            calibrated_tanks = {
                (row.tank.tank_name.casefold() if row.tank else "")
                for row in asset.calibration_table.rows
            }
            lost = sorted(removed & calibrated_tanks)
            if lost:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Tank(s) " + ", ".join(lost) + " have calibration rows. "
                        "Delete the calibration chart before removing them."
                    ),
                )
        if new_names != existing_names:
            changes.append(f"tanks: {tank_count} -> {len(tanks)}")
            _apply_tanks(asset, tanks)
            db.flush()

    calibration_required = (
        payload.calibration_required
        if payload.calibration_required is not None
        else asset.calibration_required
    )
    _validate_calibration_flag(asset_type, calibration_required, asset.tanks)
    if calibration_required != asset.calibration_required:
        changes.append(
            f"calibration_required: {'Yes' if asset.calibration_required else 'No'} -> "
            f"{'Yes' if calibration_required else 'No'}"
        )
        asset.calibration_required = calibration_required

    for field in ("dip_unit", "volume_unit", "status"):
        value = getattr(payload, field)
        if value is not None and value != getattr(asset, field):
            changes.append(f"{field}: {getattr(asset, field)} -> {value}")
            setattr(asset, field, value)

    for field in ("serial_number", "manufacturer", "model", "description"):
        value = getattr(payload, field)
        if value is not None:
            cleaned = clean_optional_text(value)
            if cleaned != getattr(asset, field):
                changes.append(f"{field} updated")
                setattr(asset, field, cleaned)

    if payload.commission_date is not None and payload.commission_date != asset.commission_date:
        changes.append(f"commission_date: {asset.commission_date} -> {payload.commission_date}")
        asset.commission_date = payload.commission_date

    asset.updated_at = utcnow()

    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Update Asset",
        current_user=actor,
        request=request,
        entity_type="Asset",
        entity_id=asset.id,
        entity_label=_asset_summary(asset),
        remarks="Asset updated",
        details_summary="; ".join(changes) or "no field changes",
        new_status=asset.status,
    )
    db.commit()
    return asset_to_dict(_get_asset(db, actor, asset.id))


@router.delete("/{asset_id}")
def deactivate_asset(
    asset_id: int,
    request: Request,
    actor: User = Depends(require_permission("assets:delete")),
    db: Session = Depends(get_db),
):
    asset = _get_asset(db, actor, asset_id)
    if asset.status != "Active":
        raise HTTPException(status_code=409, detail="This asset is already inactive")
    old_status = asset.status
    asset.status = "Inactive"
    asset.updated_at = utcnow()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Deactivate Asset",
        current_user=actor,
        request=request,
        entity_type="Asset",
        entity_id=asset.id,
        entity_label=_asset_summary(asset),
        remarks="Asset deactivated; tanks and calibration history are retained",
        old_status=old_status,
        new_status=asset.status,
    )
    db.commit()
    return asset_to_dict(_get_asset(db, actor, asset.id))
