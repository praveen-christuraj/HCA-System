"""User Role Assignment API. The HCA relationship remains many-to-many."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies.permissions import (
    get_user_permissions,
    is_admin_user,
    require_permission,
)
from app.models import Role, User, UserRole
from app.schemas import UserRolesUpdate
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.services.serializers import user_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/user-roles", tags=["User Role Assignment"])


def _users_query(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    department: str | None,
    role_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    query = db.query(User).options(selectinload(User.roles))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.username.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
                User.department.ilike(term),
            )
        )
    if status:
        query = query.filter(User.status == status)
    if department:
        query = query.filter(User.department == department)
    if role_id:
        query = query.join(UserRole, UserRole.user_id == User.id).filter(UserRole.role_id == role_id)
    if date_from:
        query = query.filter(User.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(User.created_at <= datetime.combine(date_to, time.max))
    return query


def _assignment_user(user: User) -> dict:
    payload = user_to_dict(user)
    payload["role_count"] = len(user.roles)
    return payload


def _resolve_roles(db: Session, role_ids: list[int]) -> list[Role]:
    if len(role_ids) != len(set(role_ids)):
        raise HTTPException(status_code=422, detail="Duplicate role IDs are not allowed")
    if not role_ids:
        return []
    roles = db.query(Role).options(selectinload(Role.permissions)).filter(Role.id.in_(role_ids)).all()
    if len(roles) != len(role_ids):
        raise HTTPException(status_code=422, detail="One or more roles do not exist")
    inactive = [role.role_name for role in roles if role.status != "Active"]
    if inactive:
        raise HTTPException(status_code=422, detail="Inactive roles cannot be assigned: " + ", ".join(inactive))
    if any(role.role_name.strip().casefold() == "admin" for role in roles):
        raise HTTPException(status_code=403, detail="The reserved Admin role cannot be assigned through this page")
    return roles


def _check_assignable(actor: User, target: User, roles: list[Role], db: Session) -> None:
    if is_admin_user(actor, db):
        return
    if is_admin_user(target, db):
        raise HTTPException(status_code=403, detail="The reserved administrator account cannot be changed")
    if actor.id == target.id:
        raise HTTPException(status_code=403, detail="You cannot change your own role assignments")
    available = get_user_permissions(db, actor)
    for role in roles:
        if any(
            permission.status == "Active" and permission.permission_name not in available
            for permission in role.permissions
        ):
            raise HTTPException(status_code=403, detail="You cannot assign a role with permissions you do not hold")


def _audit_assignment_import(db: Session, request: Request, actor: User, filename: str, preview: dict, *, action: str, outcome: str, status_code: int) -> None:
    create_audit_log(
        db,
        module_name="User Role Assignment",
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=f"User role import {'committed' if action == 'Import User Roles' else 'previewed'} from {filename}",
        details_summary=(
            f"file={filename}; rows={preview['total_rows']}; valid={preview['valid_rows']}; "
            f"invalid={preview['invalid_rows']}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


@router.post("/import")
def import_user_roles(
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
                                 action="Preview User Role Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    required = {"username", "role_names"}
    missing = sorted(required - set(table["columns"]))
    requested_usernames = sorted({raw.get("username", "").strip().casefold() for raw in table["rows"] if raw.get("username", "").strip()})
    users_by_name = {}
    for offset in range(0, len(requested_usernames), 500):
        chunk = requested_usernames[offset:offset + 500]
        matches = (
            db.query(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .filter(func.lower(User.username).in_(chunk))
            .all()
        )
        users_by_name.update({user.username.strip().casefold(): user for user in matches})
    roles_by_name = {
        role.role_name.strip().casefold(): role
        for role in db.query(Role).options(selectinload(Role.permissions)).filter(Role.status == "Active").all()
        if role.role_name.strip().casefold() != "admin"
    }
    actor_is_admin = is_admin_user(actor, db)
    actor_permissions = get_user_permissions(db, actor) if not actor_is_admin else set()
    seen_users: set[str] = set()
    staged = []
    for raw in table["rows"]:
        username = raw.get("username", "").strip()
        username_key = username.casefold()
        raw_roles = raw.get("role_names", "").strip()
        role_names = [name.strip() for name in raw_roles.split(";") if name.strip()]
        role_keys = [name.casefold() for name in role_names]
        errors = []
        target = users_by_name.get(username_key)
        if not username:
            errors.append("Username is required")
        elif target is None:
            errors.append("User was not found")
        elif target.status != "Active":
            errors.append("Inactive users cannot receive role assignments")
        elif is_admin_user(target, db):
            errors.append("The reserved administrator account cannot be changed")
        if username_key and username_key in seen_users:
            errors.append("Duplicate username in file")
        if username_key:
            seen_users.add(username_key)
        if len(role_keys) != len(set(role_keys)):
            errors.append("Duplicate role name in this row")

        roles = []
        for role_name in role_names:
            role = roles_by_name.get(role_name.casefold())
            if role is None:
                errors.append(f"Unknown, inactive or reserved role: {role_name}")
            else:
                roles.append(role)
        if target is not None and not actor_is_admin:
            if target.id == actor.id:
                errors.append("You cannot change your own role assignments")
            for role in roles:
                if any(
                    permission.status == "Active" and permission.permission_name not in actor_permissions
                    for permission in role.permissions
                ):
                    errors.append(f"Role contains permissions you do not hold: {role.role_name}")
            for current_role in target.roles:
                if any(
                    permission.status == "Active" and permission.permission_name not in actor_permissions
                    for permission in current_role.permissions
                ):
                    errors.append("Current role set contains permissions outside your access")
                    break
        staged.append({
            "row_number": raw["row_number"],
            "username": username,
            "role_names": "; ".join(role.role_name for role in roles),
            "_user_id": target.id if target else None,
            "_role_ids": [role.id for role in roles],
            "errors": errors,
        })

    rows = [
        {
            "row_number": row["row_number"],
            "username": row["username"],
            "role_names": row["role_names"],
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
                                 action="Preview User Role Import", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Preview User Role Import", outcome="Success", status_code=200)
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        _audit_assignment_import(db, request, actor, filename, preview,
                                 action="Import User Roles", outcome="Failure", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    for row in staged:
        db.query(UserRole).filter(UserRole.user_id == row["_user_id"]).delete(synchronize_session=False)
        for role_id in row["_role_ids"]:
            db.add(UserRole(user_id=row["_user_id"], role_id=role_id, created_at=utcnow()))
        target = db.get(User, row["_user_id"])
        if target:
            target.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="User Role Assignment",
        action="Import User Roles",
        category="Import",
        current_user=actor,
        request=request,
        remarks=f"User role assignments imported from {filename}",
        details_summary=f"file={filename}; users={total}; role_links={sum(len(row['_role_ids']) for row in staged)}",
        status_code=201,
    )
    db.commit()
    preview["imported"] = total
    preview["message"] = f"Role assignments imported for {total} user(s)"
    return preview


@router.get("")
def list_user_role_assignments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    department: str | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    users_user: User = Depends(require_permission("users:read")),
    roles_user: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    query = _users_query(
        db,
        search=search,
        status=status,
        department=department,
        role_id=role_id,
        date_from=date_from,
        date_to=date_to,
    ).order_by(User.full_name.asc(), User.id.asc())
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [_assignment_user(user) for user in result["items"]]
    result["statuses"] = [
        value for (value,) in db.query(User.status).distinct().order_by(User.status).all()
    ]
    result["departments"] = [
        value
        for (value,) in db.query(User.department)
        .filter(User.department.isnot(None), User.department != "")
        .distinct()
        .order_by(User.department)
        .all()
    ]
    return result


@router.get("/export")
def export_user_role_assignments(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    department: str | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("users:read")),
    roles_user: User = Depends(require_permission("roles:read")),
    db: Session = Depends(get_db),
):
    records = (
        _users_query(
            db,
            search=search,
            status=status,
            department=department,
            role_id=role_id,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(User.full_name.asc(), User.id.asc())
        .limit(50000)
        .all()
    )
    headers = ["Username", "Full name", "Email", "Department", "Status", "Roles", "Created"]
    rows = [
        [
            user.username,
            user.full_name,
            user.email,
            user.department or "",
            user.status,
            ", ".join(role.role_name for role in user.roles) or "No role",
            user.created_at,
        ]
        for user in records
    ]
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"department={department}" if department else "",
            f"role_id={role_id}" if role_id else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name="User Role Assignment",
        action="Export User Role Assignments",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"User role assignments exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response("user-roles", "User Role Assignment", headers, rows, [20, 26, 32, 22, 14, 42, 22])
    if format == "pdf":
        return pdf_response(
            "user-roles", "User Role Assignment", headers, rows,
            [24, 30, 38, 26, 18, 54, 26], filters_summary=filters_summary,
        )
    return csv_response("user-roles", headers, rows)


@router.put("/{user_id}")
def replace_user_roles(
    user_id: int,
    payload: UserRolesUpdate,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    target = (
        db.query(User)
        .options(selectinload(User.roles))
        .filter(User.id == user_id)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.status != "Active":
        raise HTTPException(status_code=422, detail="Only active users can receive role assignments")

    roles = _resolve_roles(db, payload.role_ids)
    _check_assignable(actor, target, roles, db)
    current_roles = list(target.roles)
    if not is_admin_user(actor, db):
        _check_assignable(actor, target, current_roles, db)
    current_ids = {role.id for role in current_roles}
    requested_ids = {role.id for role in roles}
    if current_ids == requested_ids:
        return _assignment_user(target)

    db.query(UserRole).filter(UserRole.user_id == target.id).delete(synchronize_session=False)
    for role in roles:
        db.add(UserRole(user_id=target.id, role_id=role.id, created_at=utcnow()))
    target.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="User Role Assignment",
        action="Update User Roles",
        category="Administration",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=f"{target.full_name} ({target.username})",
        request=request,
        remarks="User role assignment set replaced",
        details_summary=(
            f"username={target.username}; added={len(requested_ids - current_ids)}; "
            f"removed={len(current_ids - requested_ids)}; "
            f"roles={', '.join(role.role_name for role in roles) or 'none'}"
        ),
    )
    db.commit()
    updated = (
        db.query(User)
        .options(selectinload(User.roles))
        .filter(User.id == target.id)
        .first()
    )
    return _assignment_user(updated)


@router.delete("/{user_id}/{role_id}")
def remove_user_role(
    user_id: int,
    role_id: int,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    target = db.query(User).options(selectinload(User.roles)).filter(User.id == user_id).first()
    role = db.get(Role, role_id)
    if target is None or role is None:
        raise HTTPException(status_code=404, detail="User or role not found")
    if role.role_name.strip().casefold() == "admin" or is_admin_user(target, db):
        raise HTTPException(status_code=403, detail="The reserved administrator assignment cannot be removed")
    if not is_admin_user(actor, db):
        if actor.id == target.id:
            raise HTTPException(status_code=403, detail="You cannot change your own role assignments")
        _check_assignable(actor, target, [role], db)
        _check_assignable(actor, target, list(target.roles), db)
    assignment = db.query(UserRole).filter(
        UserRole.user_id == target.id,
        UserRole.role_id == role.id,
    ).first()
    if assignment is None:
        raise HTTPException(status_code=404, detail="User role assignment not found")
    db.delete(assignment)
    create_audit_log(
        db,
        module_name="User Role Assignment",
        action="Remove User Role",
        category="Administration",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=f"{target.full_name} ({target.username})",
        request=request,
        remarks="User role assignment removed",
        details_summary=f"username={target.username}; role={role.role_name}",
    )
    db.commit()
    return {"message": "User role assignment removed"}
