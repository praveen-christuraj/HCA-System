"""Operation Master (Configurations): location-scoped operations.

An operation is a named activity a location performs under one of the fixed
operation types (Tank, Barge, Shuttle, FSO, Tanker, Flowmeter) and one of the
fixed categories (Opening Stock, Receipt, Dispatch, and so on). The category
decides the stock sign, which is written from the catalogue on every save.

Operation Entry reads the active rows of this master to fill its dropdowns, so
the rules here are what keep that data clean:

* a type and a category must come from the hard-coded catalogue,
* the location must be Active and inside the user's assigned scope,
* the code and the label are each unique per location and operation type,
  ignoring case,
* deactivation keeps the row, so historical entries keep their meaning.
"""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import get_user_location_ids, require_permission
from app.models import Location, Operation, User
from app.schemas import OperationCreate, OperationUpdate
from app.services.audit_service import create_audit_log
from app.services.serializers import operation_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import clean_optional_text
from app.utils.operation_types import (
    OPERATION_CATEGORY_CODES,
    operation_category_catalog,
    operation_sign_catalog,
    operation_type_catalog,
    resolve_operation_category_code,
    resolve_operation_type_code,
    sign_for_category,
)
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/operations", tags=["Operation Master"])

MODULE_NAME = "Operation Master"
STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"

IMPORT_TEMPLATE_HEADERS = [
    "location_code",
    "operation_type",
    "operation_category",
    "operation_code",
    "operation_label",
    "sort_order",
    "description",
    "status",
]

_IMPORT_ALIASES = {
    "location": "location_code",
    "type": "operation_type",
    "category": "operation_category",
    "code": "operation_code",
    "label": "operation_label",
    "name": "operation_label",
    "sort": "sort_order",
}


# ---------------------------------------------------------------------------
# Scope and lookup helpers
# ---------------------------------------------------------------------------
def _scoped_operations(db: Session, user: User):
    query = db.query(Operation).options(joinedload(Operation.location))
    allowed = get_user_location_ids(db, user)
    if allowed is None:
        return query
    if not allowed:
        return query.filter(Operation.id.is_(None))
    return query.filter(Operation.location_id.in_(sorted(allowed)))


def _get_operation(db: Session, user: User, operation_id: int) -> Operation:
    operation = _scoped_operations(db, user).filter(Operation.id == operation_id).first()
    if operation is None:
        raise HTTPException(status_code=404, detail="Operation not found")
    return operation


def _location_options(db: Session, user: User) -> list[dict]:
    query = db.query(Location)
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        if not allowed:
            return []
        query = query.filter(Location.id.in_(sorted(allowed)))
    return [
        {
            "id": location.id,
            "location_name": location.location_name,
            "location_code": location.location_code,
            "status": location.status,
        }
        for location in query.order_by(Location.location_code.asc()).all()
    ]


def _filtered_operations(
    db: Session,
    user: User,
    *,
    search: str | None,
    status: str | None,
    operation_type_code: str | None,
    operation_category: str | None,
    location_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    query = _scoped_operations(db, user)
    if search:
        term = f"%{search.strip()}%"
        query = query.join(Location, Location.id == Operation.location_id).filter(
            or_(
                Operation.operation_code.ilike(term),
                Operation.operation_label.ilike(term),
                Operation.description.ilike(term),
                Location.location_name.ilike(term),
                Location.location_code.ilike(term),
            )
        )
    if status:
        query = query.filter(Operation.status == status)
    if operation_type_code:
        resolved = resolve_operation_type_code(operation_type_code)
        query = query.filter(
            Operation.operation_type_code == (resolved or operation_type_code.strip().upper())
        )
    if operation_category:
        resolved = resolve_operation_category_code(operation_category)
        query = query.filter(
            Operation.operation_category == (resolved or operation_category.strip().upper())
        )
    if location_id is not None:
        query = query.filter(Operation.location_id == location_id)
    if date_from:
        query = query.filter(Operation.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Operation.created_at <= datetime.combine(date_to, time.max))
    return query


def _operation_label(operation: Operation) -> str:
    location = operation.location.location_code if operation.location else str(operation.location_id)
    return f"{location} / {operation.operation_code} {operation.operation_label}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate_operation_fields(
    db: Session,
    actor: User,
    *,
    location_id: int,
    operation_type_code: str,
    operation_category: str,
    operation_code: str,
    operation_label: str,
    status: str,
    exclude_id: int | None = None,
) -> tuple[Location, str, str, str, str]:
    """Return (location, type code, category code, sign, normalised code)."""
    type_code = resolve_operation_type_code(operation_type_code)
    if type_code is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown operation type '{operation_type_code}'. Operation types are fixed: "
                + ", ".join(item["name"] for item in operation_type_catalog())
            ),
        )
    category_code = resolve_operation_category_code(operation_category)
    if category_code is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown operation category '{operation_category}'. Categories are fixed: "
                + ", ".join(OPERATION_CATEGORY_CODES)
            ),
        )
    sign = sign_for_category(category_code)

    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=422, detail="The selected location was not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and location.id not in allowed:
        raise HTTPException(status_code=403, detail="That location is not in your assigned scope")
    if status == STATUS_ACTIVE and location.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=422,
            detail="Only an Active location can have Active operations",
        )

    code = operation_code.strip().upper()
    label = operation_label.strip()
    clash_code = (
        db.query(Operation.id)
        .filter(
            Operation.location_id == location.id,
            Operation.operation_type_code == type_code,
            func.upper(Operation.operation_code) == code,
            Operation.id != (exclude_id or -1),
        )
        .first()
    )
    if clash_code:
        raise HTTPException(
            status_code=409,
            detail="An operation with this code already exists at this location for this operation type",
        )
    clash_label = (
        db.query(Operation.id)
        .filter(
            Operation.location_id == location.id,
            Operation.operation_type_code == type_code,
            func.lower(func.trim(Operation.operation_label)) == label.lower(),
            Operation.id != (exclude_id or -1),
        )
        .first()
    )
    if clash_label:
        raise HTTPException(
            status_code=409,
            detail="An operation with this name already exists at this location for this operation type",
        )
    return location, type_code, category_code, sign, code


# ---------------------------------------------------------------------------
# Reference and list
# ---------------------------------------------------------------------------
@router.get("")
def list_operations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    operation_type_code: str | None = None,
    operation_category: str | None = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("operations:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_operations(
        db,
        user,
        search=search,
        status=status,
        operation_type_code=operation_type_code,
        operation_category=operation_category,
        location_id=location_id,
        date_from=date_from,
        date_to=date_to,
    ).order_by(
        Operation.location_id.asc(),
        Operation.operation_type_code.asc(),
        Operation.sort_order.asc(),
        Operation.operation_label.asc(),
    )
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [operation_to_dict(item) for item in result["items"]]
    result["operation_types"] = operation_type_catalog()
    result["operation_categories"] = operation_category_catalog()
    result["signs"] = operation_sign_catalog()
    result["locations"] = _location_options(db, user)
    return result


@router.get("/export")
def export_operations(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    operation_type_code: str | None = None,
    operation_category: str | None = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("operations:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_operations(
            db,
            actor,
            search=search,
            status=status,
            operation_type_code=operation_type_code,
            operation_category=operation_category,
            location_id=location_id,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(
            Operation.location_id.asc(),
            Operation.operation_type_code.asc(),
            Operation.sort_order.asc(),
            Operation.operation_label.asc(),
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Location code",
        "Location",
        "Operation type",
        "Asset type",
        "Category",
        "Stock sign",
        "Operation code",
        "Operation",
        "Sort order",
        "Description",
        "Status",
        "Created",
    ]
    rows = []
    for operation in records:
        item = operation_to_dict(operation)
        rows.append(
            [
                item["location_code"],
                item["location_name"],
                item["operation_type_name"],
                item["asset_type_name"],
                item["operation_category_label"],
                item["operation_sign"],
                item["operation_code"],
                item["operation_label"],
                item["sort_order"],
                item["description"],
                item["status"],
                item["created_at"],
            ]
        )
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"type={operation_type_code}" if operation_type_code else "",
            f"category={operation_category}" if operation_category else "",
            f"location_id={location_id}" if location_id is not None else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Export Operations",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Operation master exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response(
            "operations",
            "Operation Master",
            headers,
            rows,
            [14, 26, 22, 18, 18, 12, 18, 30, 12, 36, 12, 22],
        )
    if format == "pdf":
        return pdf_response(
            "operations",
            "Operation Master",
            headers,
            rows,
            [14, 24, 22, 18, 18, 12, 18, 28, 12, 30, 12, 22],
            filters_summary=filters_summary,
        )
    return csv_response("operations", headers, rows)


# ---------------------------------------------------------------------------
# Import (preview, then commit). Create only: an existing code or name is a
# conflict, so an import can never silently rewrite a configured operation.
# ---------------------------------------------------------------------------
@router.post("/import")
def import_operations(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("operations:create")),
    db: Session = Depends(get_db),
):
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
            action="Preview Operation Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Operation import preview failed for {file.filename or 'upload'}",
            details_summary=str(exc),
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    rows_source = []
    for raw in table["rows"]:
        row = dict(raw)
        for alias, canonical in _IMPORT_ALIASES.items():
            if canonical not in row and alias in row:
                row[canonical] = row[alias]
        rows_source.append(row)
    columns = set(table["columns"])
    for alias, canonical in _IMPORT_ALIASES.items():
        if alias in columns:
            columns.add(canonical)
    required = {"location_code", "operation_type", "operation_category", "operation_code", "operation_label"}
    missing = sorted(required - columns)

    locations_by_code = {
        str(code).strip().upper(): location
        for code, location in db.query(Location.location_code, Location).all()
    }
    allowed = get_user_location_ids(db, actor)
    existing_codes: set[tuple] = set()
    existing_labels: set[tuple] = set()
    for row in db.query(Operation).all():
        existing_codes.add((row.location_id, row.operation_type_code, row.operation_code.strip().upper()))
        existing_labels.add((row.location_id, row.operation_type_code, row.operation_label.strip().lower()))

    prepared = []
    staged: set[tuple] = set()
    for raw in rows_source:
        errors: list[str] = []
        location_code = str(raw.get("location_code", "")).strip().upper()
        type_text = str(raw.get("operation_type", "")).strip()
        category_text = str(raw.get("operation_category", "")).strip()
        code = str(raw.get("operation_code", "")).strip().upper()
        label = str(raw.get("operation_label", "")).strip()
        status = str(raw.get("status", "") or "Active").strip().title() or "Active"
        sort_text = str(raw.get("sort_order", "") or "0").strip()
        description = str(raw.get("description", "") or "").strip()

        type_code = resolve_operation_type_code(type_text) if type_text else None
        category_code = resolve_operation_category_code(category_text) if category_text else None
        if not location_code:
            errors.append("Location code is required")
        if not type_text:
            errors.append("Operation type is required")
        elif type_code is None:
            errors.append(f"Unknown operation type '{type_text}'")
        if not category_text:
            errors.append("Operation category is required")
        elif category_code is None:
            errors.append(f"Unknown operation category '{category_text}'")
        if not code:
            errors.append("Operation code is required")
        elif len(code) > 40:
            errors.append("Operation code must be 40 characters or fewer")
        if not label:
            errors.append("Operation name is required")
        elif len(label) < 2 or len(label) > 150:
            errors.append("Operation name must be between 2 and 150 characters")
        if status not in {STATUS_ACTIVE, STATUS_INACTIVE}:
            errors.append("Status must be Active or Inactive")
        try:
            sort_order = int(float(sort_text))
            if sort_order < 0:
                raise ValueError
        except ValueError:
            sort_order = 0
            errors.append("Sort order must be a whole number of 0 or more")

        location = locations_by_code.get(location_code) if location_code else None
        if location_code and location is None:
            errors.append(f"Location code not found: {location_code}")
        elif location is not None:
            if allowed is not None and location.id not in allowed:
                errors.append(f"Location {location_code} is not in your assigned scope")
            if status == STATUS_ACTIVE and location.status != STATUS_ACTIVE:
                errors.append(f"Location {location_code} is not Active")

        if location is not None and type_code and code and label:
            key_code = (location.id, type_code, code)
            key_label = (location.id, type_code, label.lower())
            if key_code in existing_codes:
                errors.append("Operation code already exists for this location and operation type")
            if key_label in existing_labels:
                errors.append("Operation name already exists for this location and operation type")
            if key_code in staged or key_label in staged:
                errors.append("Duplicate operation code or name in file for this location and type")
            staged.add(key_code)
            staged.add(key_label)

        prepared.append(
            {
                "row_number": raw["row_number"],
                "location_code": location_code,
                "location": location,
                "operation_type_code": type_code,
                "operation_category": category_code,
                "operation_code": code,
                "operation_label": label,
                "sort_order": sort_order,
                "description": description,
                "status": status,
                "errors": errors,
            }
        )

    preview_rows = [
        {
            "row_number": row["row_number"],
            "location_code": row["location_code"],
            "operation_type": row["operation_type_code"] or "",
            "operation_category": row["operation_category"] or "",
            "operation_sign": sign_for_category(row["operation_category"]) if row["operation_category"] else "",
            "operation_code": row["operation_code"],
            "operation_label": row["operation_label"],
            "sort_order": row["sort_order"],
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
            action="Preview Operation Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Operation import preview rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; missing={', '.join(missing) or 'none'}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Operation Import",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Operation import previewed from {table['filename']}",
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
            action="Import Operations",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Operation import rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; invalid={total - valid}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    try:
        for row in prepared:
            db.add(
                Operation(
                    location_id=row["location"].id,
                    operation_type_code=row["operation_type_code"],
                    operation_category=row["operation_category"],
                    operation_sign=sign_for_category(row["operation_category"]),
                    operation_code=row["operation_code"],
                    operation_label=row["operation_label"],
                    sort_order=row["sort_order"],
                    description=clean_optional_text(row["description"]),
                    status=row["status"],
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Import Operations",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Operation import committed from {table['filename']}",
            details_summary=f"file={table['filename']}; rows={total}; imported={valid}; invalid=0",
            status_code=201,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="One or more operations already exist")
    preview["imported"] = valid
    preview["message"] = f"{valid} operation(s) imported successfully"
    return preview


# ---------------------------------------------------------------------------
# Create, read, update, deactivate
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_operation(
    payload: OperationCreate,
    request: Request,
    actor: User = Depends(require_permission("operations:create")),
    db: Session = Depends(get_db),
):
    location, type_code, category_code, sign, code = _validate_operation_fields(
        db,
        actor,
        location_id=payload.location_id,
        operation_type_code=payload.operation_type_code,
        operation_category=payload.operation_category,
        operation_code=payload.operation_code,
        operation_label=payload.operation_label,
        status=payload.status,
    )
    operation = Operation(
        location_id=location.id,
        operation_type_code=type_code,
        operation_category=category_code,
        operation_sign=sign,
        operation_code=code,
        operation_label=payload.operation_label.strip(),
        sort_order=payload.sort_order,
        description=clean_optional_text(payload.description),
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    operation.location = location
    db.add(operation)
    db.flush()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Create Operation",
        current_user=actor,
        request=request,
        entity_type="Operation",
        entity_id=operation.id,
        entity_label=_operation_label(operation),
        remarks="Operation added to the location master",
        details_summary=(
            f"location={location.location_code}; type={type_code}; "
            f"category={category_code}; sign={sign}"
        ),
        new_status=operation.status,
        status_code=201,
    )
    db.commit()
    return operation_to_dict(_get_operation(db, actor, operation.id))


@router.get("/{operation_id}")
def get_operation(
    operation_id: int,
    user: User = Depends(require_permission("operations:read")),
    db: Session = Depends(get_db),
):
    return operation_to_dict(_get_operation(db, user, operation_id))


@router.put("/{operation_id}")
def update_operation(
    operation_id: int,
    payload: OperationUpdate,
    request: Request,
    actor: User = Depends(require_permission("operations:update")),
    db: Session = Depends(get_db),
):
    operation = _get_operation(db, actor, operation_id)
    before = {
        "location": operation.location.location_code if operation.location else "",
        "type": operation.operation_type_code,
        "category": operation.operation_category,
        "code": operation.operation_code,
        "label": operation.operation_label,
        "sort_order": operation.sort_order,
        "description": operation.description or "",
        "status": operation.status,
    }
    old_status = operation.status

    merged_location_id = payload.location_id if payload.location_id is not None else operation.location_id
    merged_type = payload.operation_type_code or operation.operation_type_code
    merged_category = payload.operation_category or operation.operation_category
    merged_code = payload.operation_code or operation.operation_code
    merged_label = payload.operation_label or operation.operation_label
    merged_status = payload.status or operation.status

    location, type_code, category_code, sign, code = _validate_operation_fields(
        db,
        actor,
        location_id=merged_location_id,
        operation_type_code=merged_type,
        operation_category=merged_category,
        operation_code=merged_code,
        operation_label=merged_label,
        status=merged_status,
        exclude_id=operation.id,
    )
    operation.location_id = location.id
    operation.location = location
    operation.operation_type_code = type_code
    operation.operation_category = category_code
    operation.operation_sign = sign
    operation.operation_code = code
    operation.operation_label = merged_label.strip()
    if payload.sort_order is not None:
        operation.sort_order = payload.sort_order
    if payload.description is not None:
        operation.description = clean_optional_text(payload.description)
    operation.status = merged_status
    operation.updated_at = utcnow()

    after = {
        "location": location.location_code,
        "type": type_code,
        "category": category_code,
        "code": code,
        "label": operation.operation_label,
        "sort_order": operation.sort_order,
        "description": operation.description or "",
        "status": operation.status,
    }
    changes = [
        f"{key}: {before[key]} -> {after[key]}"
        for key in after
        if before[key] != after[key] and key != "description"
    ]
    if before["description"] != after["description"]:
        changes.append("description updated")
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Update Operation",
        current_user=actor,
        request=request,
        entity_type="Operation",
        entity_id=operation.id,
        entity_label=_operation_label(operation),
        remarks="Operation updated",
        details_summary="; ".join(changes) or "no field changes",
        old_status=old_status,
        new_status=operation.status,
    )
    db.commit()
    return operation_to_dict(_get_operation(db, actor, operation.id))


@router.delete("/{operation_id}")
def deactivate_operation(
    operation_id: int,
    request: Request,
    actor: User = Depends(require_permission("operations:delete")),
    db: Session = Depends(get_db),
):
    operation = _get_operation(db, actor, operation_id)
    if operation.status != STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="This operation is already inactive")
    old_status = operation.status
    operation.status = STATUS_INACTIVE
    operation.updated_at = utcnow()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Deactivate Operation",
        current_user=actor,
        request=request,
        entity_type="Operation",
        entity_id=operation.id,
        entity_label=_operation_label(operation),
        remarks="Operation deactivated; the record is kept for history",
        old_status=old_status,
        new_status=operation.status,
    )
    db.commit()
    return operation_to_dict(_get_operation(db, actor, operation.id))
