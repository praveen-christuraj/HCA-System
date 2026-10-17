"""Role Master and role-permission assignment API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Permission, Role, RolePermission, User, UserRole
from app.schemas import RoleCreate, RolePermissionUpdate
from app.services.audit_service import create_audit_log
from app.services.serializers import permission_to_dict, role_to_dict
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/roles", tags=["Role Master"])

RESERVED_ROLE = "Admin"


def _is_reserved(role: Role) -> bool:
    return str(role.role_name or "").strip().casefold() == RESERVED_ROLE.casefold()


@router.get("")
def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    user: User = Depends(require_permission("View Role")),
    db: Session = Depends(get_db),
):
    query = db.query(Role)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(Role.role_name.ilike(term), Role.description.ilike(term))
        )
    if status:
        query = query.filter(Role.status == status)

    result = paginate_query(query.order_by(Role.role_name.asc()), page=page, page_size=page_size)
    items = []
    for role in result["items"]:
        payload = role_to_dict(role)
        payload["permission_count"] = (
            db.query(RolePermission.id).filter(RolePermission.role_id == role.id).count()
        )
        payload["user_count"] = (
            db.query(UserRole.id).filter(UserRole.role_id == role.id).count()
        )
        payload["is_reserved"] = _is_reserved(role)
        items.append(payload)
    result["items"] = items
    return result


@router.post("", status_code=201)
def create_role(
    payload: RoleCreate,
    request: Request,
    actor: User = Depends(require_permission("Create Role")),
    db: Session = Depends(get_db),
):
    name = payload.role_name.strip()
    if name.casefold() == RESERVED_ROLE.casefold():
        raise HTTPException(status_code=409, detail="The reserved Admin role already exists")
    if db.query(Role).filter(func.lower(Role.role_name) == name.lower()).first():
        raise HTTPException(status_code=409, detail="Role name already exists")

    role = Role(
        role_name=name,
        description=(payload.description or "").strip() or None,
        status=payload.status or "Active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(role)
    db.flush()

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
    return role_to_dict(role)


@router.put("/{role_id}")
def update_role(
    role_id: int,
    payload: RoleCreate,
    request: Request,
    actor: User = Depends(require_permission("Edit Role")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if _is_reserved(role):
        raise HTTPException(status_code=422, detail="The reserved Admin role cannot be renamed")

    name = payload.role_name.strip()
    duplicate = (
        db.query(Role.id)
        .filter(func.lower(Role.role_name) == name.lower(), Role.id != role.id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Role name already exists")

    old_status = role.status
    role.role_name = name
    role.description = (payload.description or "").strip() or None
    role.status = payload.status or "Active"
    role.updated_at = utcnow()

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
        details_summary=f"role_name={role.role_name}; status={role.status}",
        old_status=old_status,
        new_status=role.status,
    )
    db.commit()
    return role_to_dict(role)


@router.get("/{role_id}/permissions")
def role_permissions(
    role_id: int,
    user: User = Depends(require_permission("View Role Permission Assignment")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
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
        "role": role_to_dict(role),
        "is_reserved": _is_reserved(role),
        "permission_ids": [permission.id for permission in rows],
        "items": [permission_to_dict(permission) for permission in rows],
    }


@router.put("/{role_id}/permissions")
def update_role_permissions(
    role_id: int,
    payload: RolePermissionUpdate,
    request: Request,
    actor: User = Depends(require_permission("Edit Role Permission Assignment")),
    db: Session = Depends(get_db),
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if _is_reserved(role):
        raise HTTPException(
            status_code=422,
            detail="The reserved Admin role always holds the full permission catalog",
        )

    permissions = (
        db.query(Permission)
        .filter(Permission.id.in_(payload.permission_ids))
        .all()
        if payload.permission_ids
        else []
    )
    if len(permissions) != len(set(payload.permission_ids)):
        raise HTTPException(status_code=422, detail="One or more permissions do not exist")

    current_ids = {
        permission_id
        for (permission_id,) in db.query(RolePermission.permission_id)
        .filter(RolePermission.role_id == role.id)
        .all()
    }
    requested_ids = {permission.id for permission in permissions}
    added_ids = requested_ids - current_ids
    removed_ids = current_ids - requested_ids

    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete(
        synchronize_session=False
    )
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
            f"role_id={role.id}; added={len(added_ids)}; removed={len(removed_ids)}; "
            f"total={len(requested_ids)}"
        ),
    )
    db.commit()
    return {
        "role": role_to_dict(role),
        "permission_ids": sorted(requested_ids),
        "added": len(added_ids),
        "removed": len(removed_ids),
        "total": len(requested_ids),
    }
