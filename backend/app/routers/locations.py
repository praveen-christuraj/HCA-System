"""Location Master — soft-coded, hierarchical and permission-gated."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Asset, Location, RoleLocation, User
from app.schemas import LocationCreate, LocationUpdate
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.services.serializers import location_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/locations", tags=["Location Master"])


def _normalise_code(value: str) -> str:
    return value.strip().upper()


def _filtered_locations(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    location_type: str | None,
    parent_location_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    query = db.query(Location).options(joinedload(Location.parent_location))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Location.location_name.ilike(term),
                Location.location_code.ilike(term),
                Location.location_type.ilike(term),
                Location.description.ilike(term),
            )
        )
    if status:
        query = query.filter(Location.status == status)
    if location_type:
        query = query.filter(Location.location_type == location_type)
    if parent_location_id is not None:
        query = query.filter(Location.parent_location_id == parent_location_id)
    if date_from:
        query = query.filter(Location.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Location.created_at <= datetime.combine(date_to, time.max))
    return query


def _validate_parent(
    db: Session,
    parent_id: int | None,
    *,
    location_id: int | None = None,
) -> Location | None:
    if parent_id is None:
        return None
    parent = db.get(Location, parent_id)
    if parent is None:
        raise HTTPException(status_code=422, detail="Parent location was not found")
    if parent.status != "Active":
        raise HTTPException(status_code=422, detail="An inactive location cannot be selected as a parent")
    seen: set[int] = set()
    cursor: Location | None = parent
    while cursor is not None:
        if cursor.id == location_id:
            raise HTTPException(status_code=422, detail="A location cannot be its own ancestor")
        if cursor.id in seen:
            raise HTTPException(status_code=409, detail="The existing location hierarchy contains a cycle")
        seen.add(cursor.id)
        cursor = db.get(Location, cursor.parent_location_id) if cursor.parent_location_id else None
    return parent


def _audit_import(
    db: Session,
    request: Request,
    actor: User,
    filename: str,
    preview: dict,
    *,
    action: str,
    outcome: str,
    status_code: int,
) -> None:
    create_audit_log(
        db,
        module_name="Location Master",
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=f"Location import {'committed' if action == 'Import Locations' else 'previewed'} from {filename}",
        details_summary=(
            f"file={filename}; rows={preview['total_rows']}; valid={preview['valid_rows']}; "
            f"invalid={preview['invalid_rows']}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


@router.get("")
def list_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_type: str | None = None,
    parent_location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("locations:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_locations(
        db,
        search=search,
        status=status,
        location_type=location_type,
        parent_location_id=parent_location_id,
        date_from=date_from,
        date_to=date_to,
    ).order_by(Location.location_code.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [location_to_dict(item) for item in result["items"]]
    result["statuses"] = [
        value
        for (value,) in db.query(Location.status).distinct().order_by(Location.status).all()
    ]
    result["location_types"] = [
        value
        for (value,) in db.query(Location.location_type).distinct().order_by(Location.location_type).all()
    ]
    return result


@router.get("/export")
def export_locations(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_type: str | None = None,
    parent_location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("locations:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_locations(
            db,
            search=search,
            status=status,
            location_type=location_type,
            parent_location_id=parent_location_id,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(Location.location_code.asc())
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = ["Location name", "Code", "Type", "Parent location", "Description", "Status", "Created"]
    rows = [
        [
            location.location_name,
            location.location_code,
            location.location_type,
            (
                f"{location.parent_location.location_name} ({location.parent_location.location_code})"
                if location.parent_location
                else ""
            ),
            location.description or "",
            location.status,
            location.created_at,
        ]
        for location in records
    ]
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"location_type={location_type}" if location_type else "",
            f"parent_location_id={parent_location_id}" if parent_location_id else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name="Location Master",
        action="Export Locations",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Location register exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response("locations", "Location Master", headers, rows, [28, 14, 20, 32, 38, 14, 22])
    if format == "pdf":
        return pdf_response(
            "locations", "Location Master", headers, rows, [30, 18, 24, 36, 46, 16, 26],
            filters_summary=filters_summary,
        )
    return csv_response("locations", headers, rows)


@router.post("/import")
def import_locations(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("locations:create")),
    db: Session = Depends(get_db),
):
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
        _audit_import(db, request, actor, file.filename or "upload", preview,
                      action="Preview Location Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    aliases = {
        "name": "location_name",
        "code": "location_code",
        "type": "location_type",
        "parent_location": "parent_location_code",
        "parent_code": "parent_location_code",
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
    required = {"location_name", "location_code", "location_type"}
    missing = sorted(required - columns)

    existing_by_code = {
        str(code).strip().casefold(): location
        for code, location in db.query(Location.location_code, Location).all()
    }
    staged_codes: set[str] = set()
    prepared = []
    for raw in rows_source:
        name = raw.get("location_name", "").strip()
        code = _normalise_code(raw.get("location_code", ""))
        location_type = raw.get("location_type", "").strip()
        parent_code = _normalise_code(raw.get("parent_location_code", "")) if raw.get("parent_location_code") else ""
        status = raw.get("status", "Active").strip() or "Active"
        errors = []
        if not name:
            errors.append("Location name is required")
        elif len(name) > 150:
            errors.append("Location name must be 150 characters or fewer")
        if not code:
            errors.append("Location code is required")
        elif len(code) > 50:
            errors.append("Location code must be 50 characters or fewer")
        if not location_type:
            errors.append("Location type is required")
        elif len(location_type) > 100:
            errors.append("Location type must be 100 characters or fewer")
        if status not in {"Active", "Inactive"}:
            errors.append("Status must be Active or Inactive")
        if code.casefold() in existing_by_code:
            errors.append("Location code already exists")
        if code and code.casefold() in staged_codes:
            errors.append("Duplicate location code in file")
        if code:
            staged_codes.add(code.casefold())
        if parent_code and parent_code.casefold() == code.casefold():
            errors.append("A location cannot be its own parent")
        prepared.append({
            "row_number": raw["row_number"],
            "location_name": name,
            "location_code": code,
            "location_type": location_type,
            "parent_location_code": parent_code,
            "description": raw.get("description", "").strip(),
            "status": status,
            "errors": errors,
        })

    staged_by_code = {
        row["location_code"].casefold(): row
        for row in prepared
        if row["location_code"]
    }
    for row in prepared:
        parent_code = row["parent_location_code"]
        if not parent_code:
            continue
        parent_key = parent_code.casefold()
        existing_parent = existing_by_code.get(parent_key)
        staged_parent = staged_by_code.get(parent_key)
        if existing_parent and existing_parent.status != "Active":
            row["errors"].append("Parent location is inactive")
        elif not existing_parent and not staged_parent:
            row["errors"].append(f"Parent location code not found: {parent_code}")
        elif staged_parent and staged_parent["status"] != "Active":
            row["errors"].append("Parent location in file must be Active")

    for start in staged_by_code:
        visited: set[str] = set()
        current = start
        while current in staged_by_code:
            if current in visited:
                cycle_code = staged_by_code[current]["location_code"]
                staged_by_code[current]["errors"].append(
                    f"Parent hierarchy contains a cycle involving {cycle_code}"
                )
                break
            visited.add(current)
            parent_code = staged_by_code[current]["parent_location_code"]
            if not parent_code:
                break
            current = parent_code.casefold()

    preview_rows = [
        {
            "row_number": row["row_number"],
            "location_name": row["location_name"],
            "location_code": row["location_code"],
            "location_type": row["location_type"],
            "parent_location_code": row["parent_location_code"],
            "status": row["status"],
            "valid": len(row["errors"]) == 0,
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
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Preview Location Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Preview Location Import", outcome="Success", status_code=200)
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Import Locations", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    created_by_code: dict[str, Location] = {}
    try:
        for row in prepared:
            location = Location(
                location_name=row["location_name"],
                location_code=row["location_code"],
                location_type=row["location_type"],
                parent_location_id=None,
                description=row["description"] or None,
                status=row["status"],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(location)
            created_by_code[row["location_code"].casefold()] = location
        db.flush()
        for row in prepared:
            parent_code = row["parent_location_code"]
            if not parent_code:
                continue
            parent = created_by_code.get(parent_code.casefold()) or existing_by_code.get(parent_code.casefold())
            created_by_code[row["location_code"].casefold()].parent_location_id = parent.id
        db.flush()
        create_audit_log(
            db,
            module_name="Location Master",
            action="Import Locations",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Location import committed from {table['filename']}",
            details_summary=f"file={table['filename']}; rows={total}; imported={valid}; invalid=0",
            status_code=201,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="One or more location codes already exist")
    preview["imported"] = valid
    preview["message"] = f"{valid} location(s) imported successfully"
    return preview


@router.post("", status_code=201)
def create_location(
    payload: LocationCreate,
    request: Request,
    actor: User = Depends(require_permission("locations:create")),
    db: Session = Depends(get_db),
):
    code = _normalise_code(payload.location_code)
    if db.query(Location.id).filter(func.lower(func.trim(Location.location_code)) == code.casefold()).first():
        raise HTTPException(status_code=409, detail="Location code already exists")
    parent = _validate_parent(db, payload.parent_location_id)
    location = Location(
        location_name=payload.location_name.strip(),
        location_code=code,
        location_type=payload.location_type.strip(),
        parent_location_id=parent.id if parent else None,
        description=payload.description.strip() if payload.description else None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(location)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Location code already exists")
    create_audit_log(
        db,
        module_name="Location Master",
        action="Create Location",
        category="Data Change",
        current_user=actor,
        entity_type="Location",
        entity_id=location.id,
        entity_label=f"{location.location_name} ({location.location_code})",
        request=request,
        remarks="Location created",
        details_summary=(
            f"name={location.location_name}; code={location.location_code}; "
            f"type={location.location_type}; parent_id={location.parent_location_id}; status={location.status}"
        ),
        status_code=201,
    )
    db.commit()
    db.refresh(location)
    return location_to_dict(location)


@router.put("/{location_id}")
def update_location(
    location_id: int,
    payload: LocationUpdate,
    request: Request,
    actor: User = Depends(require_permission("locations:update")),
    db: Session = Depends(get_db),
):
    location = db.query(Location).options(joinedload(Location.parent_location)).filter(Location.id == location_id).first()
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    data = payload.model_dump(exclude_unset=True)
    old_status = location.status
    old_code = location.location_code
    old_name = location.location_name

    if "location_name" in data and data["location_name"] is not None:
        location.location_name = data["location_name"].strip()
    if "location_code" in data and data["location_code"] is not None:
        code = _normalise_code(data["location_code"])
        duplicate = db.query(Location.id).filter(
            func.lower(func.trim(Location.location_code)) == code.casefold(),
            Location.id != location.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Location code already exists")
        location.location_code = code
    if "location_type" in data and data["location_type"] is not None:
        location.location_type = data["location_type"].strip()
    if "parent_location_id" in data:
        parent = _validate_parent(db, data["parent_location_id"], location_id=location.id)
        location.parent_location_id = parent.id if parent else None
    if "description" in data:
        location.description = data["description"].strip() or None if data["description"] else None
    if data.get("status") is not None:
        location.status = data["status"]
    if location.status == "Active" and location.parent_location_id:
        parent = db.get(Location, location.parent_location_id)
        if parent is None or parent.status != "Active":
            raise HTTPException(status_code=422, detail="An active location must have an active parent")

    location.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="Location Master",
        action="Update Location",
        category="Data Change",
        current_user=actor,
        entity_type="Location",
        entity_id=location.id,
        entity_label=f"{location.location_name} ({location.location_code})",
        request=request,
        remarks="Location updated",
        details_summary=(
            f"old_name={old_name}; name={location.location_name}; old_code={old_code}; "
            f"code={location.location_code}; parent_id={location.parent_location_id}; status={location.status}"
        ),
        old_status=old_status,
        new_status=location.status,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Location code already exists")
    db.refresh(location)
    return location_to_dict(location)


@router.delete("/{location_id}")
def deactivate_location(
    location_id: int,
    request: Request,
    actor: User = Depends(require_permission("locations:delete")),
    db: Session = Depends(get_db),
):
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    active_child = db.query(Location.id).filter(
        Location.parent_location_id == location.id,
        Location.status == "Active",
    ).first()
    if active_child:
        raise HTTPException(status_code=409, detail="Deactivate or reassign active child locations first")
    assignment_count = db.query(RoleLocation.id).filter(RoleLocation.location_id == location.id).count()
    if assignment_count:
        raise HTTPException(status_code=409, detail="Remove role location assignments before deactivating this location")
    # A Local asset may only sit on an Active location (see assets._validate_scope).
    # Without this guard the location could be withdrawn from underneath an asset
    # that still points at it, leaving a record the asset router refuses to create
    # and, because update re-validates scope, refuses to edit either.
    active_asset_count = db.query(Asset.id).filter(
        Asset.location_id == location.id,
        Asset.status == "Active",
    ).count()
    if active_asset_count:
        raise HTTPException(status_code=409, detail="Deactivate or reassign active assets at this location first")

    old_status = location.status
    location.status = "Inactive"
    location.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="Location Master",
        action="Deactivate Location",
        category="Data Change",
        current_user=actor,
        entity_type="Location",
        entity_id=location.id,
        entity_label=f"{location.location_name} ({location.location_code})",
        request=request,
        remarks="Location deactivated (soft delete)",
        details_summary=f"code={location.location_code}; name={location.location_name}",
        old_status=old_status,
        new_status=location.status,
    )
    db.commit()
    return {"message": "Location deactivated", "location": location_to_dict(location)}
