"""User Master API — paginated, filterable, RBAC-gated and audited."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Role, User, UserRole
from app.schemas import AdminResetPasswordRequest, UserCreate, UserUpdate
from app.services.audit_service import create_audit_log
from app.services.serializers import role_to_dict, user_to_dict
from app.services.user_import import commit_user_import, parse_user_import
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import clean_optional_text, display_name
from app.utils.pagination import paginate_query
from app.utils.password_policy import validate_password_policy
from app.utils.security import hash_password
from app.utils.time import utcnow

router = APIRouter(prefix="/users", tags=["User Master"])

SORTABLE_FIELDS = {
    "username": User.username,
    "full_name": User.full_name,
    "email": User.email,
    "department": User.department,
    "status": User.status,
    "created_at": User.created_at,
    "last_login_at": User.last_login_at,
}


def _base_query(db: Session):
    return db.query(User).options(selectinload(User.roles))


def _apply_filters(
    query,
    *,
    search: str | None,
    status: str | None,
    department: str | None,
    role_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                User.username.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
                User.department.ilike(term),
                User.designation.ilike(term),
            )
        )
    if status:
        query = query.filter(User.status == status)
    if department:
        query = query.filter(User.department == department)
    if role_id:
        query = query.join(UserRole, UserRole.user_id == User.id).filter(
            UserRole.role_id == role_id
        )
    # Date filters are a dedicated group (owner rule 6).
    if date_from:
        query = query.filter(User.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(User.created_at <= datetime.combine(date_to, time.max))
    return query


@router.get("")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    department: str | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    user: User = Depends(require_permission("View User")),
    db: Session = Depends(get_db),
):
    query = _apply_filters(
        _base_query(db),
        search=search,
        status=status,
        department=department,
        role_id=role_id,
        date_from=date_from,
        date_to=date_to,
    )

    column = SORTABLE_FIELDS.get(sort_by, User.created_at)
    query = query.order_by(column.asc() if sort_dir.lower() == "asc" else column.desc())

    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [user_to_dict(item) for item in result["items"]]
    result["departments"] = [
        value
        for (value,) in db.query(User.department)
        .filter(User.department.isnot(None), User.department != "")
        .distinct()
        .order_by(User.department)
        .all()
    ]
    result["statuses"] = [
        value
        for (value,) in db.query(User.status).distinct().order_by(User.status).all()
    ]
    return result


@router.get("/export")
def export_users(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    department: str | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("Export User")),
    db: Session = Depends(get_db),
):
    query = _apply_filters(
        _base_query(db),
        search=search,
        status=status,
        department=department,
        role_id=role_id,
        date_from=date_from,
        date_to=date_to,
    )
    records = query.order_by(User.created_at.asc()).limit(MAX_EXPORT_ROWS).all()

    headers = [
        "Username",
        "Full Name",
        "Email",
        "Phone",
        "Department",
        "Designation",
        "Status",
        "Roles",
        "Last Sign-in",
        "Created",
    ]
    rows = [
        [
            item.username,
            item.full_name,
            item.email,
            item.phone or "",
            item.department or "",
            item.designation or "",
            item.status,
            ", ".join(role.role_name for role in item.roles) or "No role",
            item.last_login_at or "",
            item.created_at or "",
        ]
        for item in records
    ]

    filters_summary = "; ".join(
        part
        for part in [
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"department={department}" if department else "",
            f"role_id={role_id}" if role_id else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        ]
        if part
    ) or "no filters"

    create_audit_log(
        db,
        module_name="User Master",
        action="Export Users",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"User register exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()

    widths = [18, 24, 28, 16, 20, 20, 12, 26, 20, 20]
    if format == "xlsx":
        return xlsx_response("users", "User Master", headers, rows, widths)
    if format == "pdf":
        return pdf_response(
            "users",
            "User Master",
            headers,
            rows,
            [18, 25, 29, 16, 20, 20, 12, 26, 21, 21],
            filters_summary=filters_summary,
        )
    return csv_response("users", headers, rows)


def _audit_import(
    db: Session,
    request: Request,
    actor: User,
    filename: str,
    parsed: dict,
    *,
    outcome: str,
    action: str,
    status_code: int,
) -> None:
    create_audit_log(
        db,
        module_name="User Master",
        action=action,
        category="Import",
        outcome=outcome,
        current_user=actor,
        request=request,
        remarks=(
            f"User import {'committed' if action == 'Import Users' else 'previewed'} "
            f"from {filename}"
        ),
        details_summary=(
            f"file={filename}; rows={parsed['total_rows']}; valid={parsed['valid_rows']}; "
            f"invalid={parsed['invalid_rows']}"
        ),
        status_code=status_code,
    )
    db.commit()
    request.state.audit_written = True


@router.post("/import")
def import_users(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("Create User")),
    db: Session = Depends(get_db),
):
    """Preview or commit a XLSX/CSV user import.

    ``confirm=false`` (default) returns the row-level validation preview and
    does not write anything. ``confirm=true`` imports only when every row is
    valid and is fully audited.
    """
    content = file.file.read()
    parsed = parse_user_import(content, file.filename or "", db)
    preview = {key: value for key, value in parsed.items() if not key.startswith("_")}

    if parsed.get("missing_columns") or parsed["total_rows"] == 0:
        _audit_import(db, request, actor, file.filename, parsed, outcome="Failure",
                      action="Preview User Import", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    if not confirm:
        _audit_import(db, request, actor, file.filename, parsed, outcome="Success",
                      action="Preview User Import", status_code=200)
        return preview

    if parsed["invalid_rows"] > 0 or parsed["valid_rows"] == 0:
        preview["message"] = "Fix every row error before importing."
        _audit_import(db, request, actor, file.filename, parsed, outcome="Failure",
                      action="Import Users", status_code=422)
        return JSONResponse(status_code=422, content=preview)

    try:
        imported = commit_user_import(db, parsed)
        create_audit_log(
            db,
            module_name="User Master",
            action="Import Users",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"User import committed from {file.filename}",
            details_summary=(
                f"file={file.filename}; rows={parsed['total_rows']}; imported={imported}; "
                "invalid=0"
            ),
            status_code=201,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The import could not be committed. Re-check for duplicate usernames or emails.",
        )

    preview["imported"] = imported
    preview["message"] = f"{imported} user(s) imported successfully"
    return preview


@router.get("/{user_id}")
def get_user(
    user_id: int,
    current_user: User = Depends(require_permission("View User")),
    db: Session = Depends(get_db),
):
    target = _base_query(db).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_dict(target)


def _resolve_roles(db: Session, role_ids: list[int]) -> list[Role]:
    if not role_ids:
        return []
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all()
    if len(roles) != len(set(role_ids)):
        raise HTTPException(status_code=422, detail="One or more roles do not exist")
    inactive = [role.role_name for role in roles if role.status != "Active"]
    if inactive:
        raise HTTPException(
            status_code=422,
            detail="Inactive roles cannot be assigned: " + ", ".join(inactive),
        )
    return roles


@router.post("", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    actor: User = Depends(require_permission("Create User")),
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    email = str(payload.email).strip().lower()

    if db.query(User).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="Email already exists")

    validate_password_policy(payload.password)
    roles = _resolve_roles(db, payload.role_ids)

    new_user = User(
        full_name=payload.full_name.strip(),
        username=username,
        email=email,
        phone=clean_optional_text(payload.phone),
        department=clean_optional_text(payload.department),
        designation=clean_optional_text(payload.designation),
        password_hash=hash_password(payload.password),
        password_changed_at=utcnow(),
        force_password_change=bool(payload.force_password_change),
        status=payload.status,
        failed_login_count=0,
        totp_enabled=False,
        force_2fa=False,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(new_user)
    db.flush()

    for role in roles:
        db.add(UserRole(user_id=new_user.id, role_id=role.id))

    create_audit_log(
        db,
        module_name="User Master",
        action="Create User",
        category="Data Change",
        current_user=actor,
        entity_type="User",
        entity_id=new_user.id,
        entity_label=display_name(new_user),
        request=request,
        remarks="User created",
        details_summary=(
            f"username={new_user.username}; status={new_user.status}; "
            f"roles={', '.join(role.role_name for role in roles) or 'none'}"
        ),
        status_code=201,
    )
    db.commit()
    db.refresh(new_user)
    new_user.roles = roles
    return user_to_dict(new_user)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    actor: User = Depends(require_permission("Edit User")),
    db: Session = Depends(get_db),
):
    target = _base_query(db).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_status = target.status
    changes: list[str] = []

    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()
        changes.append("full_name")
    if payload.email is not None:
        email = str(payload.email).strip().lower()
        duplicate = (
            db.query(User.id)
            .filter(func.lower(User.email) == email, User.id != target.id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Email already exists")
        target.email = email
        changes.append("email")
    if payload.phone is not None:
        target.phone = clean_optional_text(payload.phone)
        changes.append("phone")
    if payload.department is not None:
        target.department = clean_optional_text(payload.department)
        changes.append("department")
    if payload.designation is not None:
        target.designation = clean_optional_text(payload.designation)
        changes.append("designation")
    if payload.force_password_change is not None:
        target.force_password_change = bool(payload.force_password_change)
        changes.append("force_password_change")
    if payload.status is not None:
        if target.id == actor.id and payload.status != "Active":
            raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
        target.status = payload.status
        changes.append("status")

    if payload.role_ids is not None:
        roles = _resolve_roles(db, payload.role_ids)
        db.query(UserRole).filter(UserRole.user_id == target.id).delete(
            synchronize_session=False
        )
        for role in roles:
            db.add(UserRole(user_id=target.id, role_id=role.id))
        changes.append("roles")

    target.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="User Master",
        action="Update User",
        category="Data Change",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        request=request,
        remarks="User updated",
        details_summary=f"username={target.username}; fields={', '.join(changes) or 'none'}",
        old_status=old_status,
        new_status=target.status,
    )
    db.commit()
    db.refresh(target)
    return user_to_dict(target)


@router.post("/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    request: Request,
    actor: User = Depends(require_permission("Edit User")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    validate_password_policy(payload.new_password)
    target.password_hash = hash_password(payload.new_password)
    target.password_changed_at = utcnow()
    target.force_password_change = bool(payload.force_password_change)
    target.failed_login_count = 0
    target.locked_until = None
    target.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="User Master",
        action="Reset Password",
        category="Security",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        request=request,
        remarks="Administrator reset the password; no password value is recorded",
        details_summary=(
            f"username={target.username}; force_change={payload.force_password_change}"
        ),
    )
    db.commit()
    return {"message": "Password reset successfully"}


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    request: Request,
    actor: User = Depends(require_permission("Delete User")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == actor.id:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")

    old_status = target.status
    target.status = "Inactive"
    target.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="User Master",
        action="Deactivate User",
        category="Data Change",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        request=request,
        remarks="User deactivated (soft delete)",
        details_summary=f"username={target.username}",
        old_status=old_status,
        new_status=target.status,
    )
    db.commit()
    return {"message": "User deactivated", "user": user_to_dict(target)}


@router.get("/{user_id}/roles")
def user_roles(
    user_id: int,
    current_user: User = Depends(require_permission("View User Role Assignment")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"items": [role_to_dict(role) for role in target.roles]}
