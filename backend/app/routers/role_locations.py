"""Role Location Assignment API using typed RoleLocation child rows."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Location, Role, RoleLocation, User
from app.schemas import RoleLocationsUpdate
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.services.serializers import location_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/role-locations", tags=["Role Location Assignment"])


def _assignment_dict(role: Role) -> dict:
    assignments = sorted(
        role.location_assignments,
        key=lambda item: item.location.location_code.casefold() if item.location else "",
    )
    locations = [location_to_dict(item.location) for item in assignments if item.location]
    return {
        "role_id": role.id,
        "role_name": role.role_name,
        "status": role.status,
        "location_ids": [item["id"] for item in locations],
        "locations": locations,
        "location_count": len(locations),
        "created_at": role.created_at,
        "updated_at": role.updated_at,
        "is_reserved": role.role_name.strip().casefold() == "admin",
    }


def _roles_query(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
):
    query = db.query(Role).options(
        selectinload(Role.location_assignments).joinedload(RoleLocation.location)
    )
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(Role.role_name.ilike(term), Role.description.ilike(term)))
    if status:
        query = query.filter(Role.status == status)
    if date_from:
        query = query.filter(Role.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Role.created_at <= datetime.combine(date_to, time.max))
    return query


def _audit_assignment_import(db: Session, request: Request, actor: User, filename: str, preview: dict, *, action: str, outcome: str, status_code: int) -> None:
    create_audit_log(
        db,
        module_name="Role Location Assignment",
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=f"Role location import {'committed' if action == 'Import Role Locations' else 'previewed'} from {filename}",
        details_summary=(
            f"file={filename}; rows={preview['total_rows']}; valid={preview['valid_rows']}; "
            f"invalid={preview['invalid_rows']}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


@router.post("/import")
def import_role_locations(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    filename = file.filename or "upload"
    try:
        table = read_master_import(file.file.read(), filename)
    except ValueError as exc:
        preview = {
            "filename": filename,
            "format": "",
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "columns_detected": [],
            "missing_columns": [],
            "rows": [],
            "message": str(exc),
        }
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Preview Role Location Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    required = {"role_name", "location_codes"}
    missing = sorted(required - set(table["columns"]))
    roles_by_name = {role.role_name.strip().casefold(): role for role in db.query(Role).all()}
    locations_by_code = {
        location.location_code.strip().casefold(): location
        for location in db.query(Location).all()
    }
    seen_roles: set[str] = set()
    staged = []
    for raw in table["rows"]:
        role_name = raw.get("role_name", "").strip()
        role_key = role_name.casefold()
        raw_codes = raw.get("location_codes", "").strip()
        codes = [code.strip().upper() for code in raw_codes.split(";") if code.strip()]
        code_keys = [code.casefold() for code in codes]
        errors = []
        role = roles_by_name.get(role_key)
        if not role_name:
            errors.append("Role name is required")
        elif role is None:
            errors.append("Role was not found")
        elif role.status != "Active":
            errors.append("Inactive roles cannot receive location assignments")
        elif role.role_name.strip().casefold() == "admin":
            errors.append("The reserved Admin role cannot receive explicit location assignments")
        if role_key and role_key in seen_roles:
            errors.append("Duplicate role in file")
        if role_key:
            seen_roles.add(role_key)
        if len(code_keys) != len(set(code_keys)):
            errors.append("Duplicate location code in this row")
        for code in codes:
            location = locations_by_code.get(code.casefold())
            if location is None:
                errors.append(f"Location code not found: {code}")
            elif location.status != "Active":
                errors.append(f"Location is inactive: {code}")
        staged.append({
            "row_number": raw["row_number"],
            "role_name": role_name,
            "location_codes": "; ".join(codes),
            "_role_id": role.id if role else None,
            "_location_ids": [locations_by_code[code.casefold()].id for code in codes if code.casefold() in locations_by_code and locations_by_code[code.casefold()].status == "Active"],
            "errors": errors,
        })

    rows = [
        {
            "row_number": row["row_number"],
            "role_name": row["role_name"],
            "location_codes": row["location_codes"],
            "valid": not row["errors"],
            "errors": row["errors"],
        }
        for row in staged
    ]
    total = len(rows)
    valid = sum(1 for row in rows if row["valid"])
    preview = {
        "filename": table["filename"],
        "format": table["format"],
        "total_rows": total,
        "valid_rows": valid,
        "invalid_rows": total - valid,
        "columns_detected": table["columns"],
        "missing_columns": missing,
        "rows": rows,
        "message": (
            "Missing required columns: " + ", ".join(missing)
            if missing
            else f"{valid} row(s) ready to import" if valid
            else "No valid assignment rows"
        ),
    }
    if missing or total == 0:
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Preview Role Location Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Preview Role Location Import", outcome="Success", status_code=200)
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Import Role Locations", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    for row in staged:
        db.query(RoleLocation).filter(RoleLocation.role_id == row["_role_id"]).delete(synchronize_session=False)
        for location_id in row["_location_ids"]:
            db.add(RoleLocation(role_id=row["_role_id"], location_id=location_id, created_at=utcnow()))
    create_audit_log(
        db,
        module_name="Role Location Assignment",
        action="Import Role Locations",
        category="Import",
        current_user=actor,
        request=request,
        remarks=f"Role location assignments imported from {filename}",
        details_summary=f"file={filename}; roles={total}; locations={sum(len(row['_location_ids']) for row in staged)}",
        status_code=201,
    )
    db.commit()
    preview["imported"] = total
    preview["message"] = f"Location assignments imported for {total} role(s)"
    return preview


@router.get("")
def list_role_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    roles_user: User = Depends(require_permission("roles:read")),
    locations_user: User = Depends(require_permission("locations:read")),
    db: Session = Depends(get_db),
):
    query = _roles_query(
        db,
        search=search,
        status=status,
        date_from=date_from,
        date_to=date_to,
    ).order_by(Role.role_name.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [_assignment_dict(role) for role in result["items"]]
    result["statuses"] = [
        value for (value,) in db.query(Role.status).distinct().order_by(Role.status).all()
    ]
    return result


@router.get("/export")
def export_role_locations(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("roles:read")),
    locations_user: User = Depends(require_permission("locations:read")),
    db: Session = Depends(get_db),
):
    roles = (
        _roles_query(
            db,
            search=search,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(Role.role_name.asc())
        .limit(50000)
        .all()
    )
    headers = ["Role", "Status", "Locations", "Location count", "Created"]
    rows = [
        [
            role.role_name,
            role.status,
            ", ".join(
                f"{assignment.location.location_name} ({assignment.location.location_code})"
                for assignment in role.location_assignments
                if assignment.location
            ) or "No locations",
            len(role.location_assignments),
            role.created_at,
        ]
        for role in roles
    ]
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name="Role Location Assignment",
        action="Export Role Locations",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Role location assignments exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response("role-locations", "Role Location Assignment", headers, rows, [24, 14, 62, 16, 22])
    if format == "pdf":
        return pdf_response(
            "role-locations", "Role Location Assignment", headers, rows,
            [30, 18, 90, 20, 30], filters_summary=filters_summary,
        )
    return csv_response("role-locations", headers, rows)


@router.get("/{role_id}")
def get_role_locations(
    role_id: int,
    roles_user: User = Depends(require_permission("roles:read")),
    locations_user: User = Depends(require_permission("locations:read")),
    db: Session = Depends(get_db),
):
    role = (
        db.query(Role)
        .options(selectinload(Role.location_assignments).joinedload(RoleLocation.location))
        .filter(Role.id == role_id)
        .first()
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return _assignment_dict(role)


@router.put("/{role_id}")
def save_role_locations(
    role_id: int,
    payload: RoleLocationsUpdate,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).options(selectinload(Role.location_assignments)).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.role_name.strip().casefold() == "admin":
        raise HTTPException(status_code=403, detail="The reserved Admin role always has unrestricted location access")
    if role.status != "Active":
        raise HTTPException(status_code=422, detail="Only active roles can receive location assignments")
    if len(payload.location_ids) != len(set(payload.location_ids)):
        raise HTTPException(status_code=422, detail="Duplicate location IDs are not allowed")

    locations = (
        db.query(Location)
        .options(joinedload(Location.parent_location))
        .filter(Location.id.in_(payload.location_ids), Location.status == "Active")
        .all()
        if payload.location_ids
        else []
    )
    if len(locations) != len(payload.location_ids):
        raise HTTPException(status_code=422, detail="One or more locations do not exist or are inactive")

    current_ids = {assignment.location_id for assignment in role.location_assignments}
    requested_ids = {location.id for location in locations}
    if current_ids == requested_ids:
        return _assignment_dict(role)

    db.query(RoleLocation).filter(RoleLocation.role_id == role.id).delete(synchronize_session=False)
    for location in locations:
        db.add(RoleLocation(role_id=role.id, location_id=location.id, created_at=utcnow()))
    create_audit_log(
        db,
        module_name="Role Location Assignment",
        action="Update Role Locations",
        category="Administration",
        current_user=actor,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        request=request,
        remarks="Role location assignment set replaced",
        details_summary=(
            f"role_id={role.id}; added={len(requested_ids - current_ids)}; "
            f"removed={len(current_ids - requested_ids)}; total={len(requested_ids)}"
        ),
    )
    db.commit()
    updated_role = (
        db.query(Role)
        .options(
            selectinload(Role.location_assignments)
            .joinedload(RoleLocation.location)
            .joinedload(Location.parent_location)
        )
        .filter(Role.id == role.id)
        .populate_existing()
        .first()
    )
    return _assignment_dict(updated_role)
