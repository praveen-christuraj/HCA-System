"""Permission Preset Master — named, reusable permission sets for roles.

A preset bundles standard ``resource:action`` permissions once so that they can
be applied to one role or to many roles in a single audited action, instead of
ticking every permission for every role. The catalog is capped
(``MAX_PERMISSION_PRESETS``, default 20 presets) and each preset must hold at
least one active permission, so an apply can never empty a role by accident.

Permissions inside a preset are stored one row per grant in
``permission_preset_items`` (owner rule 4: no JSON columns).
"""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import (
    MAX_EXPORT_ROWS,
    MAX_PERMISSION_PRESETS,
    MAX_PRESET_APPLY_ROLES,
)
from app.database import get_db
from app.dependencies.permissions import (
    get_user_permissions,
    is_admin_user,
    require_all_permissions,
    require_permission,
)
from app.models import (
    Permission,
    PermissionPreset,
    PermissionPresetItem,
    Role,
    RolePermission,
    User,
)
from app.schemas import (
    PermissionPresetApply,
    PermissionPresetCreate,
    PermissionPresetUpdate,
)
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.services.serializers import permission_preset_to_dict
from app.utils.default_permissions import STANDARD_PERMISSIONS
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/permission-presets", tags=["Permission Presets"])

MODULE_NAME = "Permission Presets"
APPLY_MODULE_NAME = "Role Permission Assignment"
RESERVED_ROLE = "Admin"
APPLY_MODES = ("replace", "add")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_reserved_role(role: Role) -> bool:
    return str(role.role_name or "").strip().casefold() == RESERVED_ROLE.casefold()


def _eager(query):
    """Load preset items and their permissions in two queries, never N+1."""
    return query.options(
        selectinload(PermissionPreset.items).selectinload(PermissionPresetItem.permission)
    )


def _preset_count(db: Session) -> int:
    """Every preset row counts against the cap, active or deactivated."""
    return db.query(func.count(PermissionPreset.id)).scalar() or 0


def _limit_payload(db: Session) -> dict:
    used = _preset_count(db)
    return {
        "preset_limit": MAX_PERMISSION_PRESETS,
        "presets_used": used,
        "presets_remaining": max(MAX_PERMISSION_PRESETS - used, 0),
    }


def _standard_permission_map(db: Session) -> dict[str, Permission]:
    """Active standard catalog permissions keyed by lower-cased name."""
    standard_names = {
        entry["permission_name"].casefold()
        for entry in STANDARD_PERMISSIONS
        if ":" in entry["permission_name"]
    }
    return {
        permission.permission_name.casefold(): permission
        for permission in db.query(Permission)
        .filter(Permission.status == "Active")
        .order_by(Permission.module_name, Permission.permission_name)
        .all()
        if permission.permission_name.casefold() in standard_names
    }


def _resolve_permissions(
    db: Session,
    permission_ids: list[int],
    actor: User,
) -> list[Permission]:
    """Validate the requested permission set and return the rows in catalog order.

    Rules mirror Role Permission Assignment: only active standard permissions
    may be stored, duplicates are rejected, and a non-administrator may never
    put a permission into a preset that they do not hold themselves.
    """
    if len(permission_ids) != len(set(permission_ids)):
        raise HTTPException(status_code=422, detail="Duplicate permission IDs are not allowed")

    permissions = (
        db.query(Permission)
        .filter(Permission.id.in_(set(permission_ids)), Permission.status == "Active")
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .all()
    )
    if len(permissions) != len(set(permission_ids)):
        raise HTTPException(
            status_code=422,
            detail="One or more permissions do not exist or are inactive",
        )
    if not permissions:
        raise HTTPException(
            status_code=422,
            detail="A preset must contain at least one active permission",
        )
    if not is_admin_user(actor, db):
        actor_permissions = get_user_permissions(db, actor)
        if any(permission.permission_name not in actor_permissions for permission in permissions):
            raise HTTPException(
                status_code=403,
                detail="You cannot add permissions you do not hold to a preset",
            )
    return permissions


def _replace_preset_items(
    db: Session,
    preset: PermissionPreset,
    permissions: list[Permission],
) -> tuple[int, int]:
    """Rewrite the preset's child rows. Returns (added, removed) counts.

    The previous rows are flushed as DELETEs before the new ones are inserted,
    because a permission that stays in the preset would otherwise collide with
    the ``unique_preset_permission`` constraint inside a single flush.
    """
    current_ids = {item.permission_id for item in preset.items}
    next_ids = {permission.id for permission in permissions}
    preset.items = []
    db.flush()
    preset.items = [
        PermissionPresetItem(permission_id=permission.id, created_at=utcnow())
        for permission in permissions
    ]
    db.flush()
    return len(next_ids - current_ids), len(current_ids - next_ids)


def _find_duplicate_name(
    db: Session,
    preset_name: str,
    *,
    exclude_id: int | None = None,
) -> PermissionPreset | None:
    query = db.query(PermissionPreset).filter(
        func.lower(func.trim(PermissionPreset.preset_name)) == preset_name.strip().casefold()
    )
    if exclude_id is not None:
        query = query.filter(PermissionPreset.id != exclude_id)
    return query.first()


def _filtered_presets(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    permission_id: int | None,
    module_name: str | None,
    date_from: date | None,
    date_to: date | None,
):
    query = _eager(db.query(PermissionPreset))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                PermissionPreset.preset_name.ilike(term),
                PermissionPreset.description.ilike(term),
            )
        )
    if status:
        query = query.filter(PermissionPreset.status == status)
    if permission_id is not None:
        query = query.filter(
            PermissionPreset.items.any(PermissionPresetItem.permission_id == permission_id)
        )
    if module_name:
        query = query.filter(
            PermissionPreset.items.any(
                PermissionPresetItem.permission.has(Permission.module_name == module_name)
            )
        )
    if date_from:
        query = query.filter(
            PermissionPreset.created_at >= datetime.combine(date_from, time.min)
        )
    if date_to:
        query = query.filter(PermissionPreset.created_at <= datetime.combine(date_to, time.max))
    return query


def _permission_keys(preset: PermissionPreset) -> str:
    """Semicolon-separated standard keys, the import/export round-trip shape."""
    keys = sorted(
        item.permission.permission_name
        for item in preset.items
        if item.permission is not None and item.permission.status == "Active"
    )
    return "; ".join(keys)


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
        module_name=MODULE_NAME,
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=(
            f"Preset import {'committed' if action == 'Import Permission Presets' else 'previewed'}"
            f" from {filename}"
        ),
        details_summary=(
            f"file={filename}; rows={preview['total_rows']}; valid={preview['valid_rows']}; "
            f"invalid={preview['invalid_rows']}; limit={MAX_PERMISSION_PRESETS}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


def _preset_or_404(db: Session, preset_id: int) -> PermissionPreset:
    preset = (
        _eager(db.query(PermissionPreset))
        .filter(PermissionPreset.id == preset_id)
        .first()
    )
    if preset is None:
        raise HTTPException(status_code=404, detail="Permission preset not found")
    return preset


# ---------------------------------------------------------------------------
# List, options and export
# ---------------------------------------------------------------------------
@router.get("")
def list_permission_presets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    permission_id: int | None = None,
    module_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("permission_presets:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_presets(
        db,
        search=search,
        status=status,
        permission_id=permission_id,
        module_name=module_name,
        date_from=date_from,
        date_to=date_to,
    ).order_by(PermissionPreset.preset_name.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [permission_preset_to_dict(preset) for preset in result["items"]]
    result["statuses"] = [
        value
        for (value,) in db.query(PermissionPreset.status)
        .distinct()
        .order_by(PermissionPreset.status)
        .all()
    ]
    result["modules"] = [
        value
        for (value,) in db.query(Permission.module_name)
        .filter(Permission.status == "Active")
        .distinct()
        .order_by(Permission.module_name)
        .all()
    ]
    result.update(_limit_payload(db))
    return result


@router.get("/options")
def preset_options(
    user: User = Depends(require_permission("permission_presets:read")),
    db: Session = Depends(get_db),
):
    """Compact active-preset list for the Role Permission Assignment page."""
    presets = (
        _filtered_presets(
            db,
            search=None,
            status="Active",
            permission_id=None,
            module_name=None,
            date_from=None,
            date_to=None,
        )
        .order_by(PermissionPreset.preset_name.asc())
        .limit(MAX_PERMISSION_PRESETS)
        .all()
    )
    payload = {
        "items": [permission_preset_to_dict(preset) for preset in presets],
        "total": len(presets),
    }
    payload.update(_limit_payload(db))
    return payload


@router.get("/export")
def export_permission_presets(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    permission_id: int | None = None,
    module_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("permission_presets:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_presets(
            db,
            search=search,
            status=status,
            permission_id=permission_id,
            module_name=module_name,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(PermissionPreset.preset_name.asc())
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Preset name",
        "Description",
        "Permission keys",
        "Permissions",
        "Modules",
        "Status",
        "Times applied",
        "Last applied",
        "Created",
    ]
    rows = []
    for preset in records:
        payload = permission_preset_to_dict(preset)
        rows.append(
            [
                preset.preset_name,
                preset.description or "",
                _permission_keys(preset),
                payload["permission_count"],
                ", ".join(payload["modules"]),
                preset.status,
                payload["times_applied"],
                preset.last_applied_at,
                preset.created_at,
            ]
        )
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"permission_id={permission_id}" if permission_id else "",
            f"module={module_name}" if module_name else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Export Permission Presets",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Permission preset catalog exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    widths = [26, 40, 74, 12, 34, 12, 14, 22, 22]
    if format == "xlsx":
        return xlsx_response(
            "permission-presets", "Permission Presets", headers, rows, widths
        )
    if format == "pdf":
        return pdf_response(
            "permission-presets",
            "Permission Presets",
            headers,
            rows,
            [26, 34, 60, 12, 30, 12, 14, 24, 24],
            filters_summary=filters_summary,
        )
    return csv_response("permission-presets", headers, rows)


# ---------------------------------------------------------------------------
# Import (preview then commit)
# ---------------------------------------------------------------------------
@router.post("/import")
def import_permission_presets(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("permission_presets:create")),
    db: Session = Depends(get_db),
):
    """Create presets from a CSV/XLSX file: one preset per row.

    Columns: ``preset_name``, ``permission_names`` (semicolon-separated standard
    keys), optional ``description`` and ``status``. The whole file is validated
    before anything is written, and the 20-preset cap is enforced per row.
    """
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
        _audit_import(
            db, request, actor, filename, preview,
            action="Preview Permission Preset Import", outcome="Failure", status_code=422,
        )
        return JSONResponse(status_code=422, content=preview)

    aliases = {
        "name": "preset_name",
        "preset": "preset_name",
        "permissions": "permission_names",
        "permission_keys": "permission_names",
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

    required = {"preset_name", "permission_names"}
    missing = sorted(required - columns)

    permissions_by_name = _standard_permission_map(db)
    existing_names = {
        str(name).strip().casefold()
        for (name,) in db.query(PermissionPreset.preset_name).all()
    }
    actor_is_admin = is_admin_user(actor, db)
    actor_permissions = set() if actor_is_admin else get_user_permissions(db, actor)
    remaining_slots = max(MAX_PERMISSION_PRESETS - _preset_count(db), 0)

    seen_names: set[str] = set()
    staged = []
    for raw in rows_source:
        name = raw.get("preset_name", "").strip()
        name_key = name.casefold()
        description = raw.get("description", "").strip()
        status = raw.get("status", "Active").strip() or "Active"
        requested = [
            key.strip().casefold()
            for key in raw.get("permission_names", "").split(";")
            if key.strip()
        ]
        errors: list[str] = []

        if not name:
            errors.append("Preset name is required")
        elif len(name) < 2 or len(name) > 120:
            errors.append("Preset name must be between 2 and 120 characters")
        if name_key and name_key in existing_names:
            errors.append("Preset name already exists")
        if name_key and name_key in seen_names:
            errors.append("Duplicate preset name in file")
        if name_key:
            seen_names.add(name_key)
        if status not in {"Active", "Inactive"}:
            errors.append("Status must be Active or Inactive")
        if not requested:
            errors.append("At least one permission key is required")
        if len(requested) != len(set(requested)):
            errors.append("Duplicate permission key in this row")

        permissions: list[Permission] = []
        for key in requested:
            permission = permissions_by_name.get(key)
            if permission is None:
                errors.append(f"Unknown or inactive standard permission: {key}")
            else:
                permissions.append(permission)
        if permissions and not actor_is_admin:
            if any(
                permission.permission_name not in actor_permissions
                for permission in permissions
            ):
                errors.append("Preset includes permissions you do not hold")

        staged.append(
            {
                "row_number": raw["row_number"],
                "preset_name": name,
                "description": description,
                "status": status,
                "permission_names": "; ".join(
                    permission.permission_name for permission in permissions
                ),
                "_permission_ids": [permission.id for permission in permissions],
                "errors": errors,
            }
        )

    # The cap is applied in file order: rows beyond the remaining slots are
    # reported instead of silently dropped.
    slots = remaining_slots
    for row in staged:
        if not row["errors"]:
            if slots <= 0:
                row["errors"].append(
                    f"Preset limit of {MAX_PERMISSION_PRESETS} reached — free a slot first"
                )
            else:
                slots -= 1

    rows = [
        {
            "row_number": row["row_number"],
            "preset_name": row["preset_name"],
            "description": row["description"],
            "status": row["status"],
            "permission_names": row["permission_names"],
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
        "preset_limit": MAX_PERMISSION_PRESETS,
        "presets_remaining": remaining_slots,
        "message": (
            "Missing required columns: " + ", ".join(missing)
            if missing
            else f"{valid} row(s) ready to import" if valid
            else "No valid rows to import"
        ),
    }

    if missing or total == 0:
        _audit_import(
            db, request, actor, table["filename"], preview,
            action="Preview Permission Preset Import", outcome="Failure", status_code=422,
        )
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        _audit_import(
            db, request, actor, table["filename"], preview,
            action="Preview Permission Preset Import", outcome="Success", status_code=200,
        )
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        _audit_import(
            db, request, actor, table["filename"], preview,
            action="Import Permission Presets", outcome="Failure", status_code=422,
        )
        return JSONResponse(status_code=422, content=preview)

    try:
        for row in staged:
            preset = PermissionPreset(
                preset_name=row["preset_name"],
                description=row["description"] or None,
                status=row["status"],
                times_applied=0,
                created_by_user_id=actor.id,
                updated_by_user_id=actor.id,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(preset)
            db.flush()
            for permission_id in row["_permission_ids"]:
                db.add(
                    PermissionPresetItem(preset_id=preset.id, permission_id=permission_id)
                )
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Import Permission Presets",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Preset import committed from {table['filename']}",
            details_summary=(
                f"file={table['filename']}; rows={total}; imported={valid}; "
                f"permissions={sum(len(row['_permission_ids']) for row in staged)}"
            ),
            status_code=201,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="One or more preset names already exist")

    preview["imported"] = valid
    preview["message"] = f"{valid} preset(s) imported successfully"
    return preview


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_permission_preset(
    payload: PermissionPresetCreate,
    request: Request,
    actor: User = Depends(require_permission("permission_presets:create")),
    db: Session = Depends(get_db),
):
    name = payload.preset_name.strip()
    used = _preset_count(db)
    if used >= MAX_PERMISSION_PRESETS:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preset limit reached ({used} of {MAX_PERMISSION_PRESETS}). "
                "Rename an existing preset, or permanently delete an unused one to free a slot."
            ),
        )
    if _find_duplicate_name(db, name):
        raise HTTPException(status_code=409, detail="A preset with this name already exists")

    permissions = _resolve_permissions(db, payload.permission_ids, actor)
    preset = PermissionPreset(
        preset_name=name,
        description=(payload.description or "").strip() or None,
        status=payload.status,
        times_applied=0,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(preset)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A preset with this name already exists")
    for permission in permissions:
        db.add(PermissionPresetItem(preset_id=preset.id, permission_id=permission.id))
    db.flush()

    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Create Permission Preset",
        category="Administration",
        current_user=actor,
        entity_type="PermissionPreset",
        entity_id=preset.id,
        entity_label=preset.preset_name,
        request=request,
        remarks="Permission preset created",
        details_summary=(
            f"name={preset.preset_name}; permissions={len(permissions)}; "
            f"modules={len({permission.module_name for permission in permissions})}; "
            f"status={preset.status}; used={used + 1}/{MAX_PERMISSION_PRESETS}"
        ),
        new_status=preset.status,
        status_code=201,
    )
    db.commit()
    preset = _preset_or_404(db, preset.id)
    response = permission_preset_to_dict(preset, include_permissions=True)
    response.update(_limit_payload(db))
    return response


@router.get("/{preset_id}")
def get_permission_preset(
    preset_id: int,
    user: User = Depends(require_permission("permission_presets:read")),
    db: Session = Depends(get_db),
):
    preset = _preset_or_404(db, preset_id)
    response = permission_preset_to_dict(preset, include_permissions=True)
    response.update(_limit_payload(db))
    return response


@router.put("/{preset_id}")
def update_permission_preset(
    preset_id: int,
    payload: PermissionPresetUpdate,
    request: Request,
    actor: User = Depends(require_permission("permission_presets:update")),
    db: Session = Depends(get_db),
):
    preset = _preset_or_404(db, preset_id)
    data = payload.model_dump(exclude_unset=True)
    old_name = preset.preset_name
    old_status = preset.status
    old_permission_ids = {item.permission_id for item in preset.items}

    if data.get("preset_name") is not None:
        name = str(data["preset_name"]).strip()
        if _find_duplicate_name(db, name, exclude_id=preset.id):
            raise HTTPException(status_code=409, detail="A preset with this name already exists")
        preset.preset_name = name
    if "description" in data:
        preset.description = (data.get("description") or "").strip() or None
    if data.get("status") is not None:
        preset.status = data["status"]

    added = removed = 0
    if data.get("permission_ids") is not None:
        permissions = _resolve_permissions(db, list(data["permission_ids"]), actor)
        added, removed = _replace_preset_items(db, preset, permissions)

    if preset.status == "Active" and not any(
        item.permission is not None and item.permission.status == "Active"
        for item in preset.items
    ):
        raise HTTPException(
            status_code=422,
            detail="An active preset must contain at least one active permission",
        )

    preset.updated_by_user_id = actor.id
    preset.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A preset with this name already exists")

    active_count = sum(
        1
        for item in preset.items
        if item.permission is not None and item.permission.status == "Active"
    )
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Update Permission Preset",
        category="Administration",
        current_user=actor,
        entity_type="PermissionPreset",
        entity_id=preset.id,
        entity_label=preset.preset_name,
        request=request,
        remarks="Permission preset updated",
        details_summary=(
            f"old_name={old_name}; name={preset.preset_name}; added={added}; removed={removed}; "
            f"permissions={active_count}"
        ),
        old_status=old_status,
        new_status=preset.status,
    )
    db.commit()
    preset = _preset_or_404(db, preset.id)
    response = permission_preset_to_dict(preset, include_permissions=True)
    response["added"] = added
    response["removed"] = removed
    response.update(_limit_payload(db))
    return response


@router.delete("/{preset_id}")
def delete_permission_preset(
    preset_id: int,
    request: Request,
    permanent: bool = Query(False),
    actor: User = Depends(require_permission("permission_presets:delete")),
    db: Session = Depends(get_db),
):
    """Deactivate a preset, or permanently remove one that was never applied.

    Deactivation is the default and keeps the preset (and its audit history)
    available for reactivation. A permanent delete frees a slot in the capped
    catalog and is only allowed while ``times_applied`` is zero, so a preset
    that shaped live roles is never erased.
    """
    preset = _preset_or_404(db, preset_id)
    old_status = preset.status
    permission_count = len(preset.items)

    if permanent:
        if int(preset.times_applied or 0) > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This preset has been applied {preset.times_applied} time(s). "
                    "Deactivate it instead so the applied history stays traceable."
                ),
            )
        name = preset.preset_name
        # The delete-orphan cascade removes the preset's permission rows.
        preset.items.clear()
        db.flush()
        db.delete(preset)
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Delete Permission Preset",
            category="Administration",
            current_user=actor,
            entity_type="PermissionPreset",
            entity_id=preset_id,
            entity_label=name,
            request=request,
            remarks="Permission preset permanently deleted (never applied)",
            details_summary=(
                f"name={name}; permissions={permission_count}; "
                f"remaining_slots={max(MAX_PERMISSION_PRESETS - _preset_count(db) + 1, 0)}"
            ),
            old_status=old_status,
            new_status="Deleted",
        )
        db.commit()
        return {
            "message": "Permission preset deleted",
            "preset_id": preset_id,
            "permanent": True,
            **_limit_payload(db),
        }

    preset.status = "Inactive"
    preset.updated_by_user_id = actor.id
    preset.updated_at = utcnow()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Deactivate Permission Preset",
        category="Administration",
        current_user=actor,
        entity_type="PermissionPreset",
        entity_id=preset.id,
        entity_label=preset.preset_name,
        request=request,
        remarks="Permission preset deactivated (soft delete)",
        details_summary=f"name={preset.preset_name}; permissions={permission_count}",
        old_status=old_status,
        new_status=preset.status,
    )
    db.commit()
    preset = _preset_or_404(db, preset.id)
    return {
        "message": "Permission preset deactivated",
        "preset": permission_preset_to_dict(preset),
        **_limit_payload(db),
    }


# ---------------------------------------------------------------------------
# Apply a preset to roles
# ---------------------------------------------------------------------------
@router.post("/{preset_id}/apply")
def apply_permission_preset(
    preset_id: int,
    payload: PermissionPresetApply,
    request: Request,
    actor: User = Depends(
        require_all_permissions("permission_presets:read", "assignments:write")
    ),
    db: Session = Depends(get_db),
):
    """Apply the preset to one or more roles in a single audited action.

    ``mode=replace`` sets each role's grants to exactly the preset;
    ``mode=add`` merges the preset in and never removes a permission. Every
    requested role is validated before any grant is rewritten, the reserved
    Admin role is refused, and a non-administrator cannot apply permissions
    they do not hold.
    """
    if payload.mode not in APPLY_MODES:
        raise HTTPException(status_code=422, detail="Apply mode must be replace or add")
    if len(payload.role_ids) > MAX_PRESET_APPLY_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_PRESET_APPLY_ROLES} roles can be updated in one request",
        )
    if len(payload.role_ids) != len(set(payload.role_ids)):
        raise HTTPException(status_code=422, detail="Duplicate role IDs are not allowed")

    preset = _preset_or_404(db, preset_id)
    if preset.status != "Active":
        raise HTTPException(
            status_code=422,
            detail="Only active presets can be applied. Reactivate the preset first."
        )
    preset_permissions = [
        item.permission
        for item in preset.items
        if item.permission is not None and item.permission.status == "Active"
    ]
    if not preset_permissions:
        raise HTTPException(
            status_code=422,
            detail="This preset contains no active permission and cannot be applied",
        )

    roles = (
        db.query(Role)
        .filter(Role.id.in_(set(payload.role_ids)))
        .order_by(Role.role_name.asc())
        .all()
    )
    found_ids = {role.id for role in roles}
    missing_ids = sorted(set(payload.role_ids) - found_ids)
    if missing_ids:
        raise HTTPException(
            status_code=422,
            detail="Role(s) not found: " + ", ".join(str(role_id) for role_id in missing_ids),
        )
    reserved = [role.role_name for role in roles if _is_reserved_role(role)]
    if reserved:
        raise HTTPException(
            status_code=403,
            detail=(
                "The reserved Admin role always holds the full permission catalog and cannot "
                f"receive a preset: {', '.join(reserved)}"
            ),
        )
    inactive = [role.role_name for role in roles if role.status != "Active"]
    if inactive:
        raise HTTPException(
            status_code=422,
            detail="Only active roles can receive a preset: " + ", ".join(inactive),
        )

    actor_is_admin = is_admin_user(actor, db)
    actor_permissions = set() if actor_is_admin else get_user_permissions(db, actor)
    if not actor_is_admin:
        if any(
            permission.permission_name not in actor_permissions
            for permission in preset_permissions
        ):
            raise HTTPException(
                status_code=403,
                detail="You cannot apply a preset containing permissions you do not hold",
            )
        if payload.mode == "replace":
            held = db.query(Permission).join(
                RolePermission, RolePermission.permission_id == Permission.id
            ).filter(
                RolePermission.role_id.in_([role.id for role in roles]),
                Permission.status == "Active",
            ).all()
            if any(permission.permission_name not in actor_permissions for permission in held):
                raise HTTPException(
                    status_code=403,
                    detail="You cannot replace a role's permissions when it holds access you do not",
                )

    preset_ids = {permission.id for permission in preset_permissions}
    now = utcnow()
    results = []
    total_added = total_removed = 0
    for role in roles:
        current_ids = {
            permission_id
            for (permission_id,) in db.query(RolePermission.permission_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .filter(RolePermission.role_id == role.id, Permission.status == "Active")
            .all()
        }
        target_ids = set(preset_ids) if payload.mode == "replace" else current_ids | preset_ids
        added_ids = target_ids - current_ids
        removed_ids = current_ids - target_ids

        db.query(RolePermission).filter(RolePermission.role_id == role.id).delete(
            synchronize_session=False
        )
        for permission_id in sorted(target_ids):
            db.add(RolePermission(role_id=role.id, permission_id=permission_id))

        create_audit_log(
            db,
            module_name=APPLY_MODULE_NAME,
            action="Apply Permission Preset",
            category="Administration",
            current_user=actor,
            entity_type="Role",
            entity_id=role.id,
            entity_label=role.role_name,
            request=request,
            remarks=f"Preset '{preset.preset_name}' applied to role ({payload.mode})",
            details_summary=(
                f"preset_id={preset.id}; preset={preset.preset_name}; mode={payload.mode}; "
                f"added={len(added_ids)}; removed={len(removed_ids)}; total={len(target_ids)}"
            ),
        )
        total_added += len(added_ids)
        total_removed += len(removed_ids)
        results.append(
            {
                "role_id": role.id,
                "role_name": role.role_name,
                "mode": payload.mode,
                "added": len(added_ids),
                "removed": len(removed_ids),
                "total": len(target_ids),
                "permission_ids": sorted(target_ids),
            }
        )

    preset.times_applied = int(preset.times_applied or 0) + len(results)
    preset.last_applied_at = now
    preset.updated_by_user_id = actor.id
    preset.updated_at = now
    db.commit()

    refreshed = _preset_or_404(db, preset.id)
    return {
        "preset": permission_preset_to_dict(refreshed),
        "mode": payload.mode,
        "roles_updated": len(results),
        "total_added": total_added,
        "total_removed": total_removed,
        "roles": results,
    }
