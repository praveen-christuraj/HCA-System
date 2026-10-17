"""Idempotent identity bootstrap: permission catalog, Admin role, administrator.

Used by:
  * the FastAPI lifespan (development convenience and resilience),
  * ``python -m app.seed_admin``, which the Docker entrypoint runs before the
    API starts (owner rule 14).

Every step is idempotent. Re-running never duplicates records or overwrites an
existing administrator password.
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.config import (
    SEED_ADMIN_DEPARTMENT,
    SEED_ADMIN_DESIGNATION,
    SEED_ADMIN_EMAIL,
    SEED_ADMIN_FULL_NAME,
    SEED_ADMIN_PASSWORD,
    SEED_ADMIN_USERNAME,
)
from app.models import Permission, Role, RolePermission, User, UserRole
from app.services.audit_service import create_audit_log
from app.utils.default_permissions import STANDARD_PERMISSIONS
from app.utils.password_policy import password_policy_errors
from app.utils.security import hash_password
from app.utils.time import utcnow

ADMIN_ROLE_NAME = "Admin"


def seed_permission_catalog(db: Session) -> tuple[int, int]:
    """Create/refresh the permission catalog. Returns (created, updated)."""
    created = 0
    updated = 0
    for entry in STANDARD_PERMISSIONS:
        permission = (
            db.query(Permission)
            .filter(
                Permission.permission_name == entry["permission_name"],
                Permission.module_name == entry["module_name"],
            )
            .first()
        )
        if permission is None:
            permission = Permission(
                permission_name=entry["permission_name"],
                module_name=entry["module_name"],
                category=entry["category"],
                action=entry["action"],
                description=entry["description"],
                status="Active",
            )
            db.add(permission)
            created += 1
        else:
            changed = False
            for field in ("category", "action", "description"):
                if getattr(permission, field) != entry[field]:
                    setattr(permission, field, entry[field])
                    changed = True
            if changed:
                updated += 1
    db.commit()
    return created, updated


def seed_admin_role(db: Session) -> Role:
    role = db.query(Role).filter(Role.role_name == ADMIN_ROLE_NAME).first()
    if role is None:
        role = Role(
            role_name=ADMIN_ROLE_NAME,
            description="Full system access. Reserved role; cannot be locked out.",
            status="Active",
        )
        db.add(role)
        db.flush()
    else:
        role.status = "Active"

    # The Admin role always holds the full active catalog.
    permission_ids = [
        permission_id
        for (permission_id,) in db.query(Permission.id)
        .filter(Permission.status == "Active")
        .all()
    ]
    existing = {
        permission_id
        for (permission_id,) in db.query(RolePermission.permission_id)
        .filter(RolePermission.role_id == role.id)
        .all()
    }
    for permission_id in permission_ids:
        if permission_id not in existing:
            db.add(RolePermission(role_id=role.id, permission_id=permission_id))
    db.commit()
    return role


def _generate_password() -> str:
    return f"Hca@{secrets.token_urlsafe(12)}"


def seed_admin_user(db: Session, password: str | None = None) -> dict:
    """Create the administrator if missing and guarantee the Admin role.

    Returns a report dict. The generated password is returned only when this
    call created the account and no password was supplied.
    """
    role = seed_admin_role(db)

    username = SEED_ADMIN_USERNAME
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        assignment = (
            db.query(UserRole)
            .filter(UserRole.user_id == existing.id, UserRole.role_id == role.id)
            .first()
        )
        if assignment is None:
            db.add(UserRole(user_id=existing.id, role_id=role.id))
            db.commit()
        return {
            "created": False,
            "username": existing.username,
            "user_id": existing.id,
            "generated_password": None,
            "message": "Administrator already exists; password left unchanged",
        }

    supplied_password = (password if password is not None else SEED_ADMIN_PASSWORD).strip()
    generated_password = None
    if supplied_password:
        errors = password_policy_errors(supplied_password)
        if errors:
            raise ValueError(
                "SEED_ADMIN_PASSWORD does not meet the password policy: " + "; ".join(errors)
            )
        admin_password = supplied_password
    else:
        admin_password = _generate_password()
        generated_password = admin_password

    user = User(
        full_name=SEED_ADMIN_FULL_NAME or "System Administrator",
        username=username,
        email=SEED_ADMIN_EMAIL,
        department=SEED_ADMIN_DEPARTMENT,
        designation=SEED_ADMIN_DESIGNATION,
        password_hash=hash_password(admin_password),
        password_changed_at=utcnow(),
        force_password_change=False,
        force_2fa=False,
        totp_enabled=False,
        failed_login_count=0,
        status="Active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))

    create_audit_log(
        db,
        module_name="System Administration",
        action="Administrator Seeded",
        category="Administration",
        entity_type="User",
        entity_id=user.id,
        entity_label=f"{user.full_name} ({user.username})",
        remarks=(
            "Administrator created automatically during application bootstrap. "
            f"Admin role assigned. Generated password: {'yes' if generated_password else 'no'}."
        ),
        details_summary=(
            f"username={user.username}; email={user.email}; "
            f"password_source={'generated' if generated_password else 'environment'}"
        ),
        actor_username="system",
        actor_full_name="System Bootstrap",
        status_code=201,
    )
    db.commit()

    return {
        "created": True,
        "username": user.username,
        "user_id": user.id,
        "generated_password": generated_password,
        "message": "Administrator created and assigned the Admin role",
    }


def bootstrap_identity(db: Session) -> dict:
    """Run the complete idempotent bootstrap and return a summary."""
    permissions_created, permissions_updated = seed_permission_catalog(db)
    role = seed_admin_role(db)
    admin_report = seed_admin_user(db)
    return {
        "permissions_created": permissions_created,
        "permissions_updated": permissions_updated,
        "admin_role_id": role.id,
        "admin": admin_report,
    }


def admin_seeded(db: Session) -> bool:
    return (
        db.query(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(Role.role_name == ADMIN_ROLE_NAME, User.status == "Active")
        .first()
        is not None
    )


def ensure_catalog_only(db: Session) -> None:
    """Seed catalog + role without creating an administrator (tests/tools)."""
    seed_permission_catalog(db)
    seed_admin_role(db)
