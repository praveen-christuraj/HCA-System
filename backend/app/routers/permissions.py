"""Permission catalog API — feeds the RBAC matrix and Permission Master."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import require_any_permission, require_permission
from app.models import Permission, User
from app.schemas import PermissionCreate
from app.services.audit_service import create_audit_log
from app.services.serializers import permission_to_dict
from app.utils.default_permissions import ACTION_ORDER, PERMISSION_CATALOG
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/permissions", tags=["Permission Master"])


@router.get("/catalog")
def permission_catalog(
    user: User = Depends(
        require_any_permission("View Permission", "View Role Permission Assignment")
    ),
    db: Session = Depends(get_db),
):
    """Return the catalog grouped category → module → permissions (with ids)."""
    rows = (
        db.query(Permission)
        .filter(Permission.status == "Active")
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .all()
    )
    by_module: dict[tuple[str, str], list[dict]] = {}
    for permission in rows:
        key = (permission.category, permission.module_name)
        by_module.setdefault(key, []).append(permission_to_dict(permission))

    order = []
    for category in PERMISSION_CATALOG:
        for module in category["modules"]:
            order.append((category["category"], module["module_name"]))
    for key in by_module:
        if key not in order:
            order.append(key)

    categories: list[dict] = []
    for category_name, module_name in order:
        permissions = by_module.get((category_name, module_name), [])
        if not permissions:
            continue
        if not categories or categories[-1]["category"] != category_name:
            categories.append({"category": category_name, "modules": []})
        categories[-1]["modules"].append(
            {"module_name": module_name, "permissions": permissions}
        )

    return {
        "categories": categories,
        "action_order": ACTION_ORDER,
        "total_permissions": len(rows),
    }


@router.get("")
def list_permissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    category: str | None = None,
    module_name: str | None = None,
    status: str | None = None,
    user: User = Depends(require_permission("View Permission")),
    db: Session = Depends(get_db),
):
    query = db.query(Permission)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Permission.permission_name.ilike(term),
                Permission.module_name.ilike(term),
                Permission.category.ilike(term),
                Permission.description.ilike(term),
            )
        )
    if category:
        query = query.filter(Permission.category == category)
    if module_name:
        query = query.filter(Permission.module_name == module_name)
    if status:
        query = query.filter(Permission.status == status)

    result = paginate_query(
        query.order_by(Permission.category, Permission.module_name, Permission.permission_name),
        page=page,
        page_size=page_size,
    )
    result["items"] = [permission_to_dict(item) for item in result["items"]]
    result["categories"] = [
        value
        for (value,) in db.query(Permission.category).distinct().order_by(Permission.category).all()
    ]
    return result


@router.post("", status_code=201)
def create_permission(
    payload: PermissionCreate,
    request: Request,
    actor: User = Depends(require_permission("Create Permission")),
    db: Session = Depends(get_db),
):
    duplicate = (
        db.query(Permission)
        .filter(
            func.lower(Permission.permission_name) == payload.permission_name.strip().lower(),
            func.lower(Permission.module_name) == payload.module_name.strip().lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Permission already exists in this module")

    permission = Permission(
        permission_name=payload.permission_name.strip(),
        module_name=payload.module_name.strip(),
        category=payload.category.strip() or "General",
        action=payload.action,
        description=(payload.description or "").strip() or None,
        status="Active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(permission)
    db.flush()

    create_audit_log(
        db,
        module_name="Permission Master",
        action="Create Permission",
        category="Administration",
        current_user=actor,
        entity_type="Permission",
        entity_id=permission.id,
        entity_label=permission.permission_name,
        request=request,
        remarks="Permission created",
        details_summary=(
            f"permission={permission.permission_name}; module={permission.module_name}; "
            f"category={permission.category}"
        ),
        status_code=201,
    )
    db.commit()
    db.refresh(permission)
    return permission_to_dict(permission)
