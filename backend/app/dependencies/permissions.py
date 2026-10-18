"""RBAC helpers and dependencies (owner rule 11).

Permissions are always read from the database; a token never carries
permission claims. The reserved Admin role bypasses individual permission
checks and can never be locked out by configuration.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Permission, Role, RolePermission, User, UserRole
from app.services.serializers import permission_to_dict, role_to_dict, user_to_dict


def get_user_role_ids(db: Session, user: User) -> set[int]:
    return {
        role_id
        for (role_id,) in db.query(UserRole.role_id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(UserRole.user_id == user.id, Role.status == "Active")
        .all()
    }


def is_admin_user(user: User | None, db: Session) -> bool:
    if user is None:
        return False
    role_names = {
        str(name or "").strip().casefold()
        for (name,) in db.query(Role.role_name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user.id, Role.status == "Active")
        .all()
    }
    if "admin" in role_names:
        return True
    # Bootstrap fallback: the seeded administrator keeps access even if its
    # role assignment was removed by accident.
    return str(user.username or "").strip().casefold() == "admin"


def get_user_permissions(db: Session, user: User) -> set[str]:
    if is_admin_user(user, db):
        return {
            str(name).strip()
            for (name,) in db.query(Permission.permission_name)
            .filter(Permission.status == "Active")
            .all()
            if str(name or "").strip()
        }

    role_ids = get_user_role_ids(db, user)
    if not role_ids:
        return set()

    rows = (
        db.query(Permission.permission_name)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .filter(
            RolePermission.role_id.in_(role_ids),
            Role.status == "Active",
            Permission.status == "Active",
        )
        .distinct()
        .all()
    )
    return {str(name).strip() for (name,) in rows if str(name or "").strip()}


def user_has_permission(db: Session, user: User, permission_name: str) -> bool:
    if is_admin_user(user, db):
        return True
    return permission_name.strip().casefold() in {
        name.casefold() for name in get_user_permissions(db, user)
    }


def require_permission(permission_name: str):
    """Dependency factory: require one named permission."""

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not user_has_permission(db, user, permission_name):
            raise HTTPException(
                status_code=403,
                detail=f"Permission required: {permission_name}",
            )
        return user

    return dependency


def require_any_permission(*permission_names: str):
    """Dependency factory: require at least one of the listed permissions."""

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if is_admin_user(user, db):
            return user
        held = {name.casefold() for name in get_user_permissions(db, user)}
        if not any(name.casefold() in held for name in permission_names):
            raise HTTPException(
                status_code=403,
                detail="Permission required: one of " + ", ".join(permission_names),
            )
        return user

    return dependency


def require_all_permissions(*permission_names: str):
    """Dependency factory: require every listed permission.

    Used where an action belongs to two capabilities at once — applying a
    permission preset reads the preset catalog (``permission_presets:read``) and
    writes role grants (``assignments:write``).
    """

    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if is_admin_user(user, db):
            return user
        held = {name.casefold() for name in get_user_permissions(db, user)}
        missing = [name for name in permission_names if name.casefold() not in held]
        if missing:
            raise HTTPException(
                status_code=403,
                detail="Permission required: " + ", ".join(missing),
            )
        return user

    return dependency


def get_user_location_ids(db: Session, user: User) -> set[int] | None:
    """Location ids a user may act on, or ``None`` when unrestricted.

    Administrators and users with ``all_locations_access`` enabled are
    unrestricted. Otherwise, effective locations are the union of locations
    granted via active roles (``RoleLocation``) and direct user-location
    grants (``UserLocation``).
    """
    from app.models import RoleLocation, UserLocation

    if is_admin_user(user, db) or bool(getattr(user, "all_locations_access", False)):
        return None

    direct_rows = (
        db.query(UserLocation.location_id)
        .filter(UserLocation.user_id == user.id)
        .distinct()
        .all()
    )
    direct_ids = {int(location_id) for (location_id,) in direct_rows}

    role_ids = get_user_role_ids(db, user)
    if not role_ids:
        return direct_ids

    rows = (
        db.query(RoleLocation.location_id)
        .filter(RoleLocation.role_id.in_(role_ids))
        .distinct()
        .all()
    )
    return {int(location_id) for (location_id,) in rows} | direct_ids


def get_user_permission_rows(db: Session, user: User) -> list[Permission]:
    if is_admin_user(user, db):
        return (
            db.query(Permission)
            .filter(Permission.status == "Active")
            .order_by(Permission.category, Permission.module_name, Permission.permission_name)
            .all()
        )

    role_ids = get_user_role_ids(db, user)
    if not role_ids:
        return []

    return (
        db.query(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .filter(
            RolePermission.role_id.in_(role_ids),
            Permission.status == "Active",
        )
        .distinct()
        .order_by(Permission.category, Permission.module_name, Permission.permission_name)
        .all()
    )


def build_logged_in_user_response(db: Session, user: User) -> dict:
    permissions = get_user_permission_rows(db, user)
    payload = user_to_dict(user)
    payload["roles"] = [role_to_dict(role) for role in user.roles]
    payload["role"] = payload["roles"][0] if payload["roles"] else None
    payload["is_admin"] = is_admin_user(user, db)
    payload["permissions"] = [permission_to_dict(permission) for permission in permissions]
    payload["security"] = {
        "force_password_change": bool(user.force_password_change),
        "force_2fa": bool(user.force_2fa),
        "totp_enabled": bool(user.totp_enabled),
        "password_changed_at": user.password_changed_at,
        "last_login_at": user.last_login_at,
        "last_login_ip": user.last_login_ip,
    }
    return payload
