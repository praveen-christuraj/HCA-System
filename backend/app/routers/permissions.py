"""Permission catalog API — feeds the RBAC matrix and Permission Master."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Permission, User
from app.schemas import PermissionCreate
from app.services.audit_service import create_audit_log
from app.services.serializers import permission_to_dict
from app.utils.default_permissions import (
    ACTION_ORDER,
    PERMISSION_CATALOG,
    STANDARD_PERMISSION_NAMES,
)
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/permissions", tags=["Permission Master"])


@router.get("/catalog")
def permission_catalog(
    user: User = Depends(require_permission("permissions:read")),
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


def _filtered_permissions(
    db: Session,
    *,
    search: str | None = None,
    category: str | None = None,
    module_name: str | None = None,
    action: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
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
    if action:
        query = query.filter(Permission.action == action)
    if status:
        query = query.filter(Permission.status == status)
    if date_from:
        query = query.filter(Permission.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(Permission.created_at <= datetime.combine(date_to, time.max))
    return query


@router.get("")
def list_permissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    category: str | None = None,
    module_name: str | None = None,
    action: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("permissions:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_permissions(
        db,
        search=search,
        category=category,
        module_name=module_name,
        action=action,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )

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
    result["modules"] = [
        value
        for (value,) in db.query(Permission.module_name).distinct().order_by(Permission.module_name).all()
    ]
    result["actions"] = [
        value
        for (value,) in db.query(Permission.action).distinct().order_by(Permission.action).all()
    ]
    return result


@router.get("/export")
def export_permissions(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    category: str | None = None,
    module_name: str | None = None,
    action: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("permissions:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_permissions(
            db,
            search=search,
            category=category,
            module_name=module_name,
            action=action,
            status=status,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = ["Capability", "Module", "Category", "Action", "Description", "Status"]
    rows = [
        [
            item.permission_name,
            item.module_name,
            item.category,
            item.action,
            item.description or "",
            item.status,
        ]
        for item in records
    ]
    create_audit_log(
        db,
        module_name="Permission Master",
        action="Export Permissions",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} permissions as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("permissions", headers, rows)
    if format == "xlsx":
        return xlsx_response("permissions", "Permissions", headers, rows)
    return pdf_response("permissions", "Permission Catalog", headers, rows)


@router.post("", status_code=201)
def create_permission(
    payload: PermissionCreate,
    request: Request,
    actor: User = Depends(require_permission("permissions:create")),
    db: Session = Depends(get_db),
):
    permission_name = payload.permission_name.strip()
    if permission_name not in STANDARD_PERMISSION_NAMES:
        raise HTTPException(
            status_code=422,
            detail="Only permissions registered in the standard resource catalog can be created",
        )
    duplicate = (
        db.query(Permission)
        .filter(
            func.lower(Permission.permission_name) == permission_name.lower(),
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
