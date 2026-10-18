"""User Location Assignment and Access Summary APIs."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import (
    get_user_location_ids,
    get_user_permission_rows,
    is_admin_user,
    require_all_permissions,
    require_permission,
)
from app.models import Location, Role, RoleLocation, User, UserLocation, UserRole
from app.services.audit_service import create_audit_log
from app.services.serializers import location_to_dict, permission_to_dict, role_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import display_name
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(tags=["User Location & Access Summary"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserLocationAssignmentPayload(StrictModel):
    location_ids: list[int] = Field(default_factory=list, max_length=500)
    all_locations_access: bool | None = None


class AllLocationsTogglePayload(StrictModel):
    all_locations_access: bool


def _user_location_summary(db: Session, user: User, locations_by_id: dict[int, Location]) -> dict:
    direct_ids = sorted(
        loc_id
        for (loc_id,) in db.query(UserLocation.location_id)
        .filter(UserLocation.user_id == user.id)
        .all()
    )
    active_role_ids = [r.id for r in user.roles if r.status == "Active"]
    role_loc_ids = (
        sorted(
            {
                loc_id
                for (loc_id,) in db.query(RoleLocation.location_id)
                .filter(RoleLocation.role_id.in_(active_role_ids))
                .all()
            }
        )
        if active_role_ids
        else []
    )
    effective_ids = sorted(set(direct_ids) | set(role_loc_ids))
    is_admin = is_admin_user(user, db)
    unrestricted = is_admin or bool(user.all_locations_access)

    return {
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "department": user.department or "",
        "status": user.status,
        "is_admin": is_admin,
        "all_locations_access": unrestricted,
        "roles": [role_to_dict(r) for r in user.roles],
        "direct_location_ids": direct_ids,
        "direct_locations": [
            location_to_dict(locations_by_id[lid])
            for lid in direct_ids
            if lid in locations_by_id
        ],
        "role_location_ids": role_loc_ids,
        "role_locations": [
            location_to_dict(locations_by_id[lid])
            for lid in role_loc_ids
            if lid in locations_by_id
        ],
        "effective_location_ids": effective_ids,
        "effective_locations": [
            location_to_dict(locations_by_id[lid])
            for lid in effective_ids
            if lid in locations_by_id
        ],
    }


def _filtered_users(
    db: Session,
    *,
    search: str | None = None,
    status: str | None = None,
    location_id: int | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
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
    if role_id:
        query = query.join(UserRole, UserRole.user_id == User.id).filter(UserRole.role_id == role_id)
    if location_id:
        direct_users = db.query(UserLocation.user_id).filter(UserLocation.location_id == location_id)
        role_users = (
            db.query(UserRole.user_id)
            .join(RoleLocation, RoleLocation.role_id == UserRole.role_id)
            .filter(RoleLocation.location_id == location_id)
        )
        query = query.filter(or_(User.id.in_(direct_users), User.id.in_(role_users), User.all_locations_access.is_(True)))
    if date_from:
        query = query.filter(User.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(User.created_at <= datetime.combine(date_to, time.max))
    return query.order_by(User.full_name.asc(), User.id.asc())


@router.get("/user-locations")
def list_user_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_id: int | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_all_permissions("users:read", "locations:read")),
    db: Session = Depends(get_db),
):
    locations_by_id = {loc.id: loc for loc in db.query(Location).order_by(Location.location_code.asc()).all()}
    query = _filtered_users(
        db,
        search=search,
        status=status,
        location_id=location_id,
        role_id=role_id,
        date_from=date_from,
        date_to=date_to,
    )
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [_user_location_summary(db, u, locations_by_id) for u in result["items"]]
    result["locations"] = [location_to_dict(loc) for loc in locations_by_id.values() if loc.status == "Active"]
    return result


@router.get("/user-locations/export")
def export_user_locations(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_id: int | None = None,
    role_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_all_permissions("users:read", "locations:read")),
    db: Session = Depends(get_db),
):
    locations_by_id = {loc.id: loc for loc in db.query(Location).all()}
    users = (
        _filtered_users(
            db,
            search=search,
            status=status,
            location_id=location_id,
            role_id=role_id,
            date_from=date_from,
            date_to=date_to,
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Username",
        "Full Name",
        "Status",
        "All Locations Access",
        "Direct Locations",
        "Role Locations",
        "Effective Locations",
    ]
    rows = []
    for u in users:
        summary = _user_location_summary(db, u, locations_by_id)
        rows.append(
            [
                summary["username"],
                summary["full_name"],
                summary["status"],
                "Yes" if summary["all_locations_access"] else "No",
                ", ".join(loc["location_code"] for loc in summary["direct_locations"]) or "None",
                ", ".join(loc["location_code"] for loc in summary["role_locations"]) or "None",
                "All Locations"
                if summary["all_locations_access"]
                else (", ".join(loc["location_code"] for loc in summary["effective_locations"]) or "Unassigned"),
            ]
        )
    create_audit_log(
        db,
        module_name="User Location Assignment",
        action="Export User Locations",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} user location rows as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("user-locations", headers, rows)
    if format == "xlsx":
        return xlsx_response("user-locations", "User Locations", headers, rows)
    return pdf_response("user-locations", "User Location Assignments", headers, rows)


@router.get("/user-locations/{user_id}")
def get_user_location_detail(
    user_id: int,
    actor: User = Depends(require_all_permissions("users:read", "locations:read")),
    db: Session = Depends(get_db),
):
    target = db.query(User).options(selectinload(User.roles)).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    locations_by_id = {loc.id: loc for loc in db.query(Location).all()}
    return _user_location_summary(db, target, locations_by_id)


@router.put("/user-locations/{user_id}")
def update_user_locations(
    user_id: int,
    payload: UserLocationAssignmentPayload,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    target = db.query(User).options(selectinload(User.roles)).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if is_admin_user(target, db) and payload.all_locations_access is False:
        raise HTTPException(
            status_code=403,
            detail="The reserved administrator always has unrestricted location access",
        )
    if target.status != "Active":
        raise HTTPException(status_code=400, detail="Only Active users can be assigned locations")

    unique_ids = sorted(set(payload.location_ids))
    if unique_ids:
        found = db.query(Location).filter(Location.id.in_(unique_ids)).all()
        if len(found) != len(unique_ids):
            raise HTTPException(status_code=400, detail="One or more selected locations were not found")
        inactive = [loc.location_code for loc in found if loc.status != "Active"]
        if inactive:
            raise HTTPException(status_code=400, detail=f"Only Active locations can be assigned: {', '.join(inactive)}")

    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        if any(lid not in allowed for lid in unique_ids):
            raise HTTPException(status_code=403, detail="Cannot assign a location outside your own scope")
        if payload.all_locations_access:
            raise HTTPException(status_code=403, detail="Only an unrestricted administrator can grant all-location access")

    before_ids = sorted(
        lid for (lid,) in db.query(UserLocation.location_id).filter(UserLocation.user_id == target.id).all()
    )
    db.query(UserLocation).filter(UserLocation.user_id == target.id).delete()
    for lid in unique_ids:
        db.add(UserLocation(user_id=target.id, location_id=lid, created_at=utcnow()))

    if payload.all_locations_access is not None:
        target.all_locations_access = bool(payload.all_locations_access)
        target.updated_at = utcnow()

    locations_by_id = {loc.id: loc for loc in db.query(Location).all()}
    before_codes = [locations_by_id[lid].location_code for lid in before_ids if lid in locations_by_id]
    after_codes = [locations_by_id[lid].location_code for lid in unique_ids if lid in locations_by_id]

    create_audit_log(
        db,
        module_name="User Location Assignment",
        action="Update User Locations",
        category="Administration",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        request=request,
        remarks=f"Updated direct locations for {target.username}",
        details_summary=(
            f"user={target.username}; before={','.join(before_codes) or 'none'}; "
            f"after={','.join(after_codes) or 'none'}; all_locations={bool(target.all_locations_access)}"
        ),
    )
    db.commit()
    db.refresh(target)
    request.state.audit_written = True
    return _user_location_summary(db, target, locations_by_id)


@router.put("/user-locations/{user_id}/all-locations-access")
def update_user_all_locations_access(
    user_id: int,
    payload: AllLocationsTogglePayload,
    request: Request,
    actor: User = Depends(require_permission("assignments:write")),
    db: Session = Depends(get_db),
):
    target = db.query(User).options(selectinload(User.roles)).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if is_admin_user(target, db):
        raise HTTPException(
            status_code=403,
            detail="The reserved administrator always has unrestricted location access",
        )
    if get_user_location_ids(db, actor) is not None:
        raise HTTPException(status_code=403, detail="Only an unrestricted administrator can change all-location access")

    before = bool(target.all_locations_access)
    target.all_locations_access = bool(payload.all_locations_access)
    target.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="User Location Assignment",
        action="Update All Locations Access",
        category="Administration",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        request=request,
        remarks=f"All locations access changed from {before} to {target.all_locations_access}",
        details_summary=f"user={target.username}; before={before}; after={target.all_locations_access}",
    )
    db.commit()
    request.state.audit_written = True
    locations_by_id = {loc.id: loc for loc in db.query(Location).all()}
    return _user_location_summary(db, target, locations_by_id)


@router.get("/access-summary")
def list_access_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    role_id: int | None = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_all_permissions("users:read", "roles:read", "permissions:read")),
    db: Session = Depends(get_db),
):
    locations_by_id = {loc.id: loc for loc in db.query(Location).order_by(Location.location_code.asc()).all()}
    query = _filtered_users(
        db,
        search=search,
        status=status,
        location_id=location_id,
        role_id=role_id,
        date_from=date_from,
        date_to=date_to,
    )
    result = paginate_query(query, page=page, page_size=page_size)
    items = []
    for u in result["items"]:
        loc_info = _user_location_summary(db, u, locations_by_id)
        perms = get_user_permission_rows(db, u)
        items.append(
            {
                **loc_info,
                "permission_count": len(perms),
                "modules_accessible": sorted({p.module_name for p in perms}),
                "permissions": [permission_to_dict(p) for p in perms],
                "totp_enabled": bool(u.totp_enabled),
                "last_login_at": u.last_login_at,
                "created_at": u.created_at,
            }
        )
    result["items"] = items
    result["roles"] = [role_to_dict(r) for r in db.query(Role).order_by(Role.role_name.asc()).all()]
    result["locations"] = [location_to_dict(loc) for loc in locations_by_id.values()]
    return result


@router.get("/access-summary/export")
def export_access_summary(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    role_id: int | None = None,
    location_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_all_permissions("users:read", "roles:read", "permissions:read")),
    db: Session = Depends(get_db),
):
    locations_by_id = {loc.id: loc for loc in db.query(Location).all()}
    users = (
        _filtered_users(
            db,
            search=search,
            status=status,
            location_id=location_id,
            role_id=role_id,
            date_from=date_from,
            date_to=date_to,
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Username",
        "Full Name",
        "Status",
        "Roles",
        "Effective Locations",
        "Permissions Count",
        "2FA Enabled",
    ]
    rows = []
    for u in users:
        loc_info = _user_location_summary(db, u, locations_by_id)
        perms = get_user_permission_rows(db, u)
        rows.append(
            [
                u.username,
                u.full_name,
                u.status,
                ", ".join(r.role_name for r in u.roles) or "No role",
                "All Locations"
                if loc_info["all_locations_access"]
                else (", ".join(loc["location_code"] for loc in loc_info["effective_locations"]) or "Unassigned"),
                len(perms),
                "Yes" if u.totp_enabled else "No",
            ]
        )
    create_audit_log(
        db,
        module_name="Access Summary",
        action="Export Access Summary",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} access summary records as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("access-summary", headers, rows)
    if format == "xlsx":
        return xlsx_response("access-summary", "Access Summary", headers, rows)
    return pdf_response("access-summary", "Access Summary Matrix", headers, rows)
