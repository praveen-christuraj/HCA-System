"""Portfolio and module-wise dashboards (owner rule 8)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import (
    is_admin_user,
    require_permission,
    user_has_permission,
)
from app.models import AuditLog, PasswordResetRequest, Permission, Role, User
from app.services.serializers import audit_to_dict, user_to_dict
from app.utils.time import utcnow

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

USER_MODULES = (
    "User Master",
    "Role Master",
    "Permission Master",
    "Role Permission Assignment",
    "User Role Assignment",
    "Profile & Security",
    "Authentication",
)

MODULE_PERMISSIONS = {
    "user-management": "View User Management Dashboard",
    "auditing": "View Auditing Dashboard",
}


def _module_definitions(db: Session, user: User) -> list[dict]:
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    user_total = db.query(func.count(User.id)).scalar() or 0
    user_active = db.query(func.count(User.id)).filter(User.status == "Active").scalar() or 0
    role_total = db.query(func.count(Role.id)).filter(Role.status == "Active").scalar() or 0
    permission_total = (
        db.query(func.count(Permission.id)).filter(Permission.status == "Active").scalar() or 0
    )
    audit_total = db.query(func.count(AuditLog.id)).scalar() or 0
    audit_today = (
        db.query(func.count(AuditLog.id)).filter(AuditLog.created_at >= today_start).scalar() or 0
    )

    return [
        {
            "key": "user-management",
            "name": "User Management",
            "status": "Foundation",
            "description": (
                "Users, roles, permissions and access control. User list is available; "
                "assignment screens are in the next increment."
            ),
            "path": "/modules/user-management",
            "permission": "View User Management Dashboard",
            "metrics": [
                {"label": "Users", "value": user_total},
                {"label": "Active users", "value": user_active},
                {"label": "Roles", "value": role_total},
                {"label": "Permissions", "value": permission_total},
            ],
        },
        {
            "key": "master-data",
            "name": "Master Data Management",
            "status": "Planned",
            "description": (
                "Locations, asset types, assets, calibration templates and reference data, "
                "extracted from OTMS with import/export and module dashboard."
            ),
            "path": "/modules/master-data",
            "permission": "View System Dashboard",
            "metrics": [],
        },
        {
            "key": "business",
            "name": "Business Operations",
            "status": "Planned",
            "description": (
                "Operation entry, transaction workflow, tank and vessel operations, "
                "export operations and movement tracking."
            ),
            "path": "/modules/business",
            "permission": "View System Dashboard",
            "metrics": [],
        },
        {
            "key": "reports",
            "name": "Report Modules",
            "status": "Planned",
            "description": (
                "Tank stock ledger, out-turn, material balance, tanker transaction and "
                "tracking reports with print-grade PDF output."
            ),
            "path": "/modules/reports",
            "permission": "View System Dashboard",
            "metrics": [],
        },
        {
            "key": "backup",
            "name": "Back-up Modules",
            "status": "Planned",
            "description": (
                "Backup settings, scheduled backup jobs, restore requests and validation, "
                "with full auditing."
            ),
            "path": "/modules/backup",
            "permission": "View System Dashboard",
            "metrics": [],
        },
        {
            "key": "auditing",
            "name": "Auditing Modules",
            "status": "Available",
            "description": (
                "Append-only audit trail for every action, security events and module "
                "activity reporting."
            ),
            "path": "/modules/auditing",
            "permission": "View Auditing Dashboard",
            "metrics": [
                {"label": "Audit events", "value": audit_total},
                {"label": "Today", "value": audit_today},
            ],
        },
        {
            "key": "system",
            "name": "System Administration",
            "status": "Foundation",
            "description": (
                "Health, seed status and deployment diagnostics. Application settings and "
                "notifications are planned."
            ),
            "path": "/modules/system",
            "permission": "View System Health",
            "metrics": [],
        },
        {
            "key": "profile",
            "name": "Profile & Security",
            "status": "Planned",
            "description": (
                "Password change, two-factor enrolment, backup codes and personal session "
                "activity."
            ),
            "path": "/modules/profile",
            "permission": "View Own Security Settings",
            "metrics": [],
        },
    ]


@router.get("/summary")
def portfolio_summary(
    user: User = Depends(require_permission("View System Dashboard")),
    db: Session = Depends(get_db),
):
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_30_days = now - timedelta(days=30)

    users_total = db.query(func.count(User.id)).scalar() or 0
    users_active = db.query(func.count(User.id)).filter(User.status == "Active").scalar() or 0
    users_locked = (
        db.query(func.count(User.id))
        .filter(User.locked_until.isnot(None), User.locked_until > now)
        .scalar()
        or 0
    )
    users_new_30 = (
        db.query(func.count(User.id)).filter(User.created_at >= last_30_days).scalar() or 0
    )
    roles_total = db.query(func.count(Role.id)).filter(Role.status == "Active").scalar() or 0
    permissions_total = (
        db.query(func.count(Permission.id)).filter(Permission.status == "Active").scalar() or 0
    )
    audit_today = (
        db.query(func.count(AuditLog.id)).filter(AuditLog.created_at >= today_start).scalar() or 0
    )
    audit_failures_today = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.created_at >= today_start, AuditLog.outcome == "Failure")
        .scalar()
        or 0
    )
    pending_resets = (
        db.query(func.count(PasswordResetRequest.id))
        .filter(PasswordResetRequest.status == "Pending")
        .scalar()
        or 0
    )

    recent = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(10)
        .all()
    )

    return {
        "generated_at": now,
        "kpis": [
            {
                "key": "active_users",
                "label": "Active users",
                "value": users_active,
                "context": f"{users_total} total - {users_locked} locked",
            },
            {
                "key": "audit_today",
                "label": "Audited actions today",
                "value": audit_today,
                "context": f"{audit_failures_today} failures",
            },
            {
                "key": "roles",
                "label": "Active roles",
                "value": roles_total,
                "context": f"{permissions_total} permissions in catalog",
            },
            {
                "key": "pending_resets",
                "label": "Pending resets",
                "value": pending_resets,
                "context": f"{users_new_30} users added in 30 days",
            },
        ],
        "modules": _module_definitions(db, user),
        "recent_audit": [audit_to_dict(entry) for entry in recent],
        "current_user": user_to_dict(user),
    }


def _require_module_access(db: Session, user: User, module_key: str) -> str:
    required = MODULE_PERMISSIONS.get(module_key, "View System Dashboard")
    if not is_admin_user(user, db) and not user_has_permission(db, user, required):
        raise HTTPException(status_code=403, detail=f"Permission required: {required}")
    return required


@router.get("/modules/{module_key}")
def module_dashboard(
    module_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    modules = {module["key"]: module for module in _module_definitions(db, user)}
    module = modules.get(module_key)
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")
    required_permission = _require_module_access(db, user, module_key)

    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    kpis: list[dict] = []
    breakdown: list[dict] = []
    quick_links: list[dict] = []
    recent_activity: list[dict] = []

    if module_key == "user-management":
        last_30_days = now - timedelta(days=30)
        users_total = db.query(func.count(User.id)).scalar() or 0
        users_active = db.query(func.count(User.id)).filter(User.status == "Active").scalar() or 0
        users_inactive = (
            db.query(func.count(User.id)).filter(User.status != "Active").scalar() or 0
        )
        users_locked = (
            db.query(func.count(User.id))
            .filter(User.locked_until.isnot(None), User.locked_until > now)
            .scalar()
            or 0
        )
        users_new = (
            db.query(func.count(User.id)).filter(User.created_at >= last_30_days).scalar() or 0
        )
        roles_total = db.query(func.count(Role.id)).filter(Role.status == "Active").scalar() or 0
        permissions_total = (
            db.query(func.count(Permission.id)).filter(Permission.status == "Active").scalar() or 0
        )

        kpis = [
            {"label": "Total users", "value": users_total, "context": "All accounts"},
            {"label": "Active users", "value": users_active, "context": "Can sign in"},
            {"label": "Inactive users", "value": users_inactive, "context": "Access revoked"},
            {"label": "Locked accounts", "value": users_locked, "context": "Temporary lockout"},
            {"label": "New in 30 days", "value": users_new, "context": "Account growth"},
            {"label": "Roles / permissions", "value": f"{roles_total} / {permissions_total}", "context": "RBAC catalog"},
        ]
        status_rows = (
            db.query(User.status, func.count(User.id)).group_by(User.status).all()
        )
        breakdown = [
            {"label": status, "value": count, "tone": "success" if status == "Active" else "neutral"}
            for status, count in status_rows
        ]
        quick_links = [
            {"label": "User Master", "path": "/users", "permission": "View User"},
            {"label": "Audit Trail", "path": "/audit", "permission": "View Audit Log"},
        ]
        activity_query = db.query(AuditLog).filter(AuditLog.module_name.in_(USER_MODULES))
    elif module_key == "auditing":
        audit_total = db.query(func.count(AuditLog.id)).scalar() or 0
        audit_today = (
            db.query(func.count(AuditLog.id)).filter(AuditLog.created_at >= today_start).scalar()
            or 0
        )
        failures_today = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.created_at >= today_start, AuditLog.outcome == "Failure")
            .scalar()
            or 0
        )
        security_total = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.category == "Security")
            .scalar()
            or 0
        )
        distinct_actors = (
            db.query(func.count(func.distinct(AuditLog.actor_username))).scalar() or 0
        )

        kpis = [
            {"label": "Total events", "value": audit_total, "context": "Append-only trail"},
            {"label": "Today", "value": audit_today, "context": f"{failures_today} failures"},
            {"label": "Security events", "value": security_total, "context": "All time"},
            {"label": "Distinct actors", "value": distinct_actors, "context": "Recorded identities"},
        ]
        category_rows = (
            db.query(AuditLog.category, func.count(AuditLog.id))
            .group_by(AuditLog.category)
            .order_by(func.count(AuditLog.id).desc())
            .limit(8)
            .all()
        )
        breakdown = [
            {"label": category, "value": count, "tone": "info"}
            for category, count in category_rows
        ]
        quick_links = [
            {"label": "Audit Trail", "path": "/audit", "permission": "View Audit Log"},
            {"label": "Home", "path": "/", "permission": "View System Dashboard"},
        ]
        activity_query = db.query(AuditLog)
    elif module_key == "system":
        users_total = db.query(func.count(User.id)).scalar() or 0
        roles_total = db.query(func.count(Role.id)).scalar() or 0
        permissions_total = db.query(func.count(Permission.id)).scalar() or 0
        audit_total = db.query(func.count(AuditLog.id)).scalar() or 0
        kpis = [
            {"label": "Users", "value": users_total, "context": "All accounts"},
            {"label": "Roles", "value": roles_total, "context": "Including reserved Admin"},
            {"label": "Permissions", "value": permissions_total, "context": "Seeded catalog"},
            {"label": "Audit events", "value": audit_total, "context": "Append-only"},
        ]
        quick_links = [{"label": "Audit Trail", "path": "/audit", "permission": "View Audit Log"}]
        activity_query = db.query(AuditLog).filter(AuditLog.module_name == "System Administration")
    else:
        activity_query = db.query(AuditLog).filter(AuditLog.module_name.ilike(f"%{module['name']}%"))

    recent_activity = [
        audit_to_dict(entry)
        for entry in activity_query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(8)
        .all()
    ]

    return {
        "module": module,
        "required_permission": required_permission,
        "kpis": kpis,
        "breakdown": breakdown,
        "quick_links": quick_links,
        "recent_activity": recent_activity,
        "planned_items": (
            [
                "Data model, API and permission catalog for the module",
                "Module dashboard with live KPIs and status breakdown",
                "List pages with server pagination, quick/advanced filters and a separate date range",
                "XLSX/CSV import and XLSX/CSV/PDF export",
                "Full audit coverage and admin-controlled RBAC",
            ]
            if module["status"] == "Planned"
            else []
        ),
        "generated_at": now,
    }
