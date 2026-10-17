"""Role Master API and role-permission assignment endpoints."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import (
    get_user_permissions,
    is_admin_user,
    require_permission,
)
from app.models import (
    Permission,
    Role,
    RoleLocation,
    RolePermission,
    User,
    UserRole,
)
from app.schemas import RoleCreate, RolePermissionUpdate
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.services.serializers import permission_to_dict, role_to_dict
from app.utils.default_permissions import STANDARD_PERMISSIONS
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/roles", tags=["Role Master"])

RESERVED_ROLE = "Admin"


def _is_reserved(role: Role) -> bool:
    return str(role.role_name or "").strip().casefold() == RESERVED_ROLE.casefold()


def _date_filters(query, created_at, date_from: date | None, date_to: date | None):
    if date_from:
        query = query.filter(created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(created_at <= datetime.combine(date_to, time.max))
    return query


def _role_payload(db: Session, role: Role) -> dict:
    payload = role_to_dict(role)
    payload["permission_count"] = (
        db.query(RolePermission.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .filter(RolePermission.role_id == role.id, Permission.status == "Active")
        .count()
    )
    payload["user_count"] = db.query(UserRole.id).filter(UserRole.role_id == role.id).count()
    payload["location_count"] = (
        db.query(RoleLocation.id)
        .filter(RoleLocation.role_id == role.id)
        .count()
    )
    payload["is_reserved"] = _is_reserved(role)
    return payload


def _filtered_roles(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
):
    query = db.query(Role)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(or_(Role.role_name.ilike(term), Role.description.ilike(term)))
    if status:
        query = query.filter(Role.status == status)
    return _date_filters(query, Role.created_at, date_from, date_to)


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
        module_name="Role Master",
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=f"Role import {'committed' if action == 'Import Roles' else 'previewed'} from {filename}",
        details_summary=(
            f"file={filename}; rows={preview['total_rows']}; valid={preview['valid_rows']}; "
            f"invalid={preview['invalid_rows']}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


@router.get("")
def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_roles(
        db,
        search=search,
        status=status,
        date_from=date_from,
        date_to=date_to,
    ).order_by(Role.role_name.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [_role_payload(db, role) for role in result["items"]]
    result["statuses"] = [
        value
        for (value,) in db.query(Role.status).distinct().order_by(Role.status).all()
    ]
    return result


@router.get("/export")
def export_roles(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_roles(
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
    headers = ["Role name", "Description", "Status", "Users", "Permissions", "Locations", "Created"]
    rows = [
        [
            role.role_name,
            role.description or "",
            role.status,
            _role_payload(db, role)["user_count"],
            _role_payload(db, role)["permission_count"],
            _role_payload(db, role)["location_count"],
            role.created_at,
        ]
        for role in records
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
        module_name="Role Master",
        action="Export Roles",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Role register exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response("roles", "Role Master", headers, rows, [24, 42, 14, 12, 14, 14, 22])
    if format == "pdf":
        return pdf_response(
            "roles", "Role Master", headers, rows, [36, 64, 20, 16, 20, 18, 30],
            filters_summary=filters_summary,
        )
    return csv_response("roles", headers, rows)


@router.post("/import")
def import_roles(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("roles:create")),
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
                      action="Preview Role Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    required = {"role_name"}
    missing = sorted(required - set(table["columns"]))
    existing_names = {
        str(name).strip().casefold()
        for (name,) in db.query(Role.role_name).all()
    }
    seen: set[str] = set()
    rows = []
    for row in table["rows"]:
        name = row.get("role_name", "").strip()
        status = row.get("status", "Active").strip() or "Active"
        errors = []
        if not name:
            errors.append("Role name is required")
        elif len(name) < 2 or len(name) > 100:
            errors.append("Role name must be between 2 and 100 characters")
        if name and name.casefold() == RESERVED_ROLE.casefold():
            errors.append("The reserved Admin role cannot be imported")
        if status not in {"Active", "Inactive"}:
            errors.append("Status must be Active or Inactive")
        if name and name.casefold() in existing_names:
            errors.append("Role name already exists")
        if name and name.casefold() in seen:
            errors.append("Duplicate role name in file")
        if name:
            seen.add(name.casefold())
        rows.append({
            "row_number": row["row_number"],
            "role_name": name,
            "description": row.get("description", ""),
            "status": status,
            "valid": not errors,
            "errors": errors,
        })

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
            else "No valid rows to import"
        ),
    }
    if missing or total == 0:
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Preview Role Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Preview Role Import", outcome="Success", status_code=200)
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        _audit_import(db, request, actor, table["filename"], preview,
                      action="Import Roles", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    try:
        for row in rows:
            db.add(Role(
                role_name=row["role_name"],
                description=row["description"].strip() or None,
                status=row["status"],
                created_at=utcnow(),
                updated_at=utcnow(),
            ))
        create_audit_log(
            db,
            module_name="Role Master",
            action="Import Roles",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Role import committed from {table['filename']}",
            details_summary=f"file={table['filename']}; rows={total}; imported={valid}; invalid=0",
            status_code=201,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A role with one of these names already exists")
    preview["imported"] = valid
    preview["message"] = f"{valid} role(s) imported successfully"
    return preview


@router.post("", status_code=201)
def create_role(
    payload: RoleCreate,
    request: Request,
    actor: User = Depends(require_permission("roles:create")),
    db: Session = Depends(get_db),
):
    name = payload.role_name.strip()
    if name.casefold() == RESERVED_ROLE.casefold():
        raise HTTPException(status_code=409, detail="The reserved Admin role already exists")
    if db.query(Role.id).filter(func.lower(func.trim(Role.role_name)) == name.casefold()).first():
        raise HTTPException(status_code=409, detail="Role name already exists")

    role = Role(
        role_name=name,
        description=(payload.description or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Role name already exists")
    create_audit_log(
        db,
        module_name="Role Master",
        action="Create Role",
        category="Data Change",
        current_user=actor,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        request=request,
        remarks="Role created",
        details_summary=f"role_name={role.role_name}; status={role.status}",
        status_code=201,
    )
    db.commit()
    db.refresh(role)
    return _role_payload(db, role)


@router.put("/{role_id}")
def update_role(
    role_id: int,
    payload: RoleCreate,
    request: Request,
    actor: User = Depends(require_permission("roles:update")),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if _is_reserved(role):
        raise HTTPException(status_code=403, detail="The reserved Admin role cannot be edited")
    if role.status == "Active" and payload.status == "Inactive" and not is_admin_user(actor, db):
        if db.query(UserRole.id).filter(UserRole.user_id == actor.id, UserRole.role_id == role.id).first():
            raise HTTPException(status_code=422, detail="You cannot deactivate a role assigned to your account")

    name = payload.role_name.strip()
    duplicate = db.query(Role.id).filter(
        func.lower(func.trim(Role.role_name)) == name.casefold(),
        Role.id != role.id,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Role name already exists")

    old_status = role.status
    old_name = role.role_name
    role.role_name = name
    role.description = (payload.description or "").strip() or None
    role.status = payload.status
    role.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Role name already exists")
    create_audit_log(
        db,
        module_name="Role Master",
        action="Update Role",
        category="Data Change",
        current_user=actor,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        request=request,
        remarks="Role updated",
        details_summary=f"old_name={old_name}; role_name={role.role_name}; status={role.status}",
        old_status=old_status,
        new_status=role.status,
    )
    db.commit()
    db.refresh(role)
    return _role_payload(db, role)


@router.delete("/{role_id}")
def deactivate_role(
    role_id: int,
    request: Request,
    actor: User = Depends(require_permission("roles:delete")),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if _is_reserved(role):
        raise HTTPException(status_code=403, detail="The reserved Admin role cannot be deactivated")
    if role.status == "Active" and not is_admin_user(actor, db):
        if db.query(UserRole.id).filter(UserRole.user_id == actor.id, UserRole.role_id == role.id).first():
            raise HTTPException(status_code=422, detail="You cannot deactivate a role assigned to your account")

    old_status = role.status
    role.status = "Inactive"
    role.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="Role Master",
        action="Deactivate Role",
        category="Data Change",
        current_user=actor,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        request=request,
        remarks="Role deactivated (soft delete); assignments are retained for audit and possible reactivation",
        details_summary=f"role_name={role.role_name}; assigned_users={db.query(UserRole.id).filter(UserRole.role_id == role.id).count()}",
        old_status=old_status,
        new_status=role.status,
    )
    db.commit()
    return {"message": "Role deactivated", "role": _role_payload(db, role)}


@router.post("/permissions/import")
def import_role_permissions(
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
        create_audit_log(
            db,
            module_name="Role Permission Assignment",
            action="Preview Role Permission Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Role permission import preview failed: {filename}",
            details_summary=f"file={filename}; rows=0; error={str(exc)[:250]}",
            status_code=422,
        )
        db.commit()
        request.state.audit_written = True
        return JSONResponse(status_code=422, content=preview)

    required = {"role_name", "permission_names"}
    missing = sorted(required - set(table["columns"]))
    roles_by_name = {role.role_name.strip().casefold(): role for role in db.query(Role).all()}
    standard_names = {
        entry["permission_name"].casefold(): entry["permission_name"]
        for entry in STANDARD_PERMISSIONS
        if ":" in entry["permission_name"]
    }
    permissions_by_name = {
        permission.permission_name.casefold(): permission
        for permission in db.query(Permission).filter(Permission.status == "Active").all()
        if permission.permission_name.casefold() in standard_names
    }
    actor_is_admin = is_admin_user(actor, db)
    actor_permissions = get_user_permissions(db, actor) if not actor_is_admin else set()
    seen_roles: set[str] = set()
    staged = []
    for raw in table["rows"]:
        role_name = raw.get("role_name", "").strip()
        role_key = role_name.casefold()
        raw_names = raw.get("permission_names", "").strip()
        requested_names = [name.strip().casefold() for name in raw_names.split(";") if name.strip()]
        errors = []
        role = roles_by_name.get(role_key)
        if not role_name:
            errors.append("Role name is required")
        elif role is None:
            errors.append("Role was not found")
        elif role.status != "Active":
            errors.append("Inactive roles cannot receive permissions")
        elif _is_reserved(role):
            errors.append("The reserved Admin role cannot be changed")
        if role_key and role_key in seen_roles:
            errors.append("Duplicate role in file")
        if role_key:
            seen_roles.add(role_key)
        if len(requested_names) != len(set(requested_names)):
            errors.append("Duplicate permission key in this row")

        permissions = []
        for permission_name in requested_names:
            canonical_name = standard_names.get(permission_name)
            permission = permissions_by_name.get(permission_name)
            if canonical_name is None or permission is None:
                errors.append(f"Unknown or inactive standard permission: {permission_name}")
            else:
                permissions.append(permission)
        if role is not None and not actor_is_admin:
            if any(permission.permission_name not in actor_permissions for permission in permissions):
                errors.append("Requested permission set includes permissions you do not hold")
            current = (
                db.query(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .filter(RolePermission.role_id == role.id, Permission.status == "Active")
                .all()
            )
            if any(permission.permission_name not in actor_permissions for permission in current):
                errors.append("Current role permission set contains permissions outside your access")
        staged.append({
            "row_number": raw["row_number"],
            "role_name": role_name,
            "permission_names": "; ".join(permission.permission_name for permission in permissions),
            "_role_id": role.id if role else None,
            "_permission_ids": [permission.id for permission in permissions],
            "errors": errors,
        })

    rows = [
        {
            "row_number": row["row_number"],
            "role_name": row["role_name"],
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
        "message": (
            "Missing required columns: " + ", ".join(missing)
            if missing
            else f"{valid} row(s) ready to import" if valid
            else "No valid assignment rows"
        ),
    }

    def audit_import(action: str, outcome: str, status_code: int) -> None:
        create_audit_log(
            db,
            module_name="Role Permission Assignment",
            action=action,
            category="Import",
            outcome=outcome,
            current_user=actor,
            request=request,
            remarks=f"Role permission import {'committed' if action == 'Import Role Permissions' else 'previewed'} from {filename}",
            details_summary=(
                f"file={filename}; rows={total}; valid={valid}; invalid={total - valid}"
            ),
            status_code=status_code,
        )
        db.commit()
        request.state.audit_written = True

    if missing or total == 0:
        audit_import("Preview Role Permission Import", "Failure", 422)
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        audit_import("Preview Role Permission Import", "Success", 200)
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        audit_import("Import Role Permissions", "Failure", 422)
        return JSONResponse(status_code=422, content=preview)

    for row in staged:
        db.query(RolePermission).filter(RolePermission.role_id == row["_role_id"]).delete(synchronize_session=False)
        for permission_id in row["_permission_ids"]:
            db.add(RolePermission(role_id=row["_role_id"], permission_id=permission_id))
    create_audit_log(
        db,
        module_name="Role Permission Assignment",
        action="Import Role Permissions",
        category="Import",
        current_user=actor,
        request=request,
        remarks=f"Role permission sets imported from {filename}",
        details_summary=f"file={filename}; roles={total}; permissions={sum(len(row['_permission_ids']) for row in staged)}",
        status_code=201,
    )
    db.commit()
    request.state.audit_written = True
    preview["imported"] = total
    preview["message"] = f"Permission sets imported for {total} role(s)"
    return preview


@router.get("/{role_id}/permissions/export")
def export_role_permissions(
    role_id: int,
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    permissions = (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.status == "Active")
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .limit(50000)
        .all()
    )
    headers = ["Role", "Permission", "Module", "Category", "Action", "Description"]
    rows = [
        [role.role_name, item.permission_name, item.module_name, item.category, item.action, item.description or ""]
        for item in permissions
    ]
    create_audit_log(
        db,
        module_name="Role Permission Assignment",
        action="Export Role Permissions",
        category="Export",
        current_user=actor,
        request=request,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        remarks=f"Permission set exported as {format.upper()}",
        details_summary=f"role={role.role_name}; format={format}; rows={len(rows)}",
    )
    db.commit()
    widths = [24, 32, 28, 24, 14, 60]
    if format == "xlsx":
        return xlsx_response("role-permissions", f"Permissions - {role.role_name}", headers, rows, widths)
    if format == "pdf":
        return pdf_response(
            "role-permissions", f"Permissions - {role.role_name}", headers, rows,
            [26, 35, 30, 26, 16, 66], filters_summary=f"role={role.role_name}",
        )
    return csv_response("role-permissions", headers, rows)


@router.get("/{role_id}/permissions")
def role_permissions(
    role_id: int,
    user: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    rows = (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.status == "Active")
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .all()
    )
    return {
        "role": _role_payload(db, role),
        "is_reserved": _is_reserved(role),
        "permission_ids": [permission.id for permission in rows],
        "items": [permission_to_dict(permission) for permission in rows],
    }


@router.put("/{role_id}/permissions")
def update_role_permissions(
    role_id: int,
    payload: RolePermissionUpdate,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if _is_reserved(role):
        raise HTTPException(status_code=403, detail="The reserved Admin role always has the full permission catalog")
    if role.status != "Active":
        raise HTTPException(status_code=422, detail="Only active roles can receive permission changes")
    if len(payload.permission_ids) != len(set(payload.permission_ids)):
        raise HTTPException(status_code=422, detail="Duplicate permission IDs are not allowed")

    permissions = (
        db.query(Permission)
        .filter(Permission.id.in_(payload.permission_ids), Permission.status == "Active")
        .all()
        if payload.permission_ids
        else []
    )
    if len(permissions) != len(payload.permission_ids):
        raise HTTPException(status_code=422, detail="One or more permissions do not exist or are inactive")

    current_permissions = (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(RolePermission.role_id == role.id, Permission.status == "Active")
        .all()
    )
    if not is_admin_user(actor, db):
        actor_permissions = get_user_permissions(db, actor)
        if any(permission.permission_name not in actor_permissions for permission in permissions):
            raise HTTPException(status_code=403, detail="You cannot grant permissions you do not hold")
        if any(permission.permission_name not in actor_permissions for permission in current_permissions):
            raise HTTPException(status_code=403, detail="You cannot change a role with permissions outside your own access")

    current_ids = {permission.id for permission in current_permissions}
    requested_ids = {permission.id for permission in permissions}
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete(synchronize_session=False)
    for permission in permissions:
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))

    create_audit_log(
        db,
        module_name="Role Permission Assignment",
        action="Update Role Permissions",
        category="Administration",
        current_user=actor,
        entity_type="Role",
        entity_id=role.id,
        entity_label=role.role_name,
        request=request,
        remarks="Role permission set replaced",
        details_summary=(
            f"role_id={role.id}; added={len(requested_ids - current_ids)}; "
            f"removed={len(current_ids - requested_ids)}; total={len(requested_ids)}"
        ),
    )
    db.commit()
    return {
        "role": _role_payload(db, role),
        "permission_ids": sorted(requested_ids),
        "added": len(requested_ids - current_ids),
        "removed": len(current_ids - requested_ids),
        "total": len(requested_ids),
    }
