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
from app.models import (
    Asset,
    AssetCalibrationRow,
    AssetCalibrationTable,
    AssetTank,
    AuditLog,
    Location,
    PasswordResetRequest,
    Permission,
    PermissionPreset,
    Role,
    RoleLocation,
    User,
)
from app.config import MAX_PERMISSION_PRESETS
from app.services.serializers import audit_to_dict, user_to_dict
from app.utils.asset_types import asset_type_catalog
from app.utils.time import utcnow

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

USER_MODULES = (
    "User Master",
    "Role Master",
    "Permission Master",
    "Permission Presets",
    "Role Permission Assignment",
    "User Role Assignment",
    "Profile & Security",
    "Authentication",
    "Location Master",
    "Role Location Assignment",
)

MASTER_DATA_MODULES = (
    "Asset Master",
    "Asset Calibration",
)

MODULE_PERMISSIONS = {
    "user-management": "users:read",
    "master-data": "assets:read",
    "business": "dashboard:read",
    "reports": "dashboard:read",
    "backup": "dashboard:read",
    "auditing": "audit:read",
    "system": "system:read",
    "profile": "profile:read",
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
    location_total = db.query(func.count(Location.id)).scalar() or 0
    location_active = db.query(func.count(Location.id)).filter(Location.status == "Active").scalar() or 0
    role_location_total = db.query(func.count(RoleLocation.id)).scalar() or 0
    preset_total = db.query(func.count(PermissionPreset.id)).scalar() or 0
    preset_active = (
        db.query(func.count(PermissionPreset.id))
        .filter(PermissionPreset.status == "Active")
        .scalar()
        or 0
    )
    asset_total = db.query(func.count(Asset.id)).scalar() or 0
    asset_active = db.query(func.count(Asset.id)).filter(Asset.status == "Active").scalar() or 0
    tank_total = db.query(func.count(AssetTank.id)).scalar() or 0
    chart_total = db.query(func.count(AssetCalibrationTable.id)).scalar() or 0

    return [
        {
            "key": "user-management",
            "name": "User Management",
            "status": "Available",
            "description": (
                "User Master, Role Master, Location Master, role permission, role location and "
                "user role assignment, with password administration and audited access control."
            ),
            "path": "/modules/user-management",
            "permission": "users:read",
            "metrics": [
                {"label": "Users", "value": user_total},
                {"label": "Active users", "value": user_active},
                {"label": "Roles", "value": role_total},
                {"label": "Permission presets", "value": f"{preset_active} / {preset_total}"},
            ],
        },
        {
            "key": "master-data",
            "name": "Master Data Management",
            "status": "Available",
            "description": (
                "Asset Master over the seven fixed hydrocarbon asset types, with tanks declared "
                "per asset and calibration charts stored in canonical cm and bbl."
            ),
            "path": "/modules/master-data",
            "permission": "assets:read",
            "metrics": [
                {"label": "Assets", "value": asset_total},
                {"label": "Active assets", "value": asset_active},
                {"label": "Tanks", "value": tank_total},
                {"label": "Calibration charts", "value": chart_total},
            ],
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
            "permission": "dashboard:read",
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
            "permission": "dashboard:read",
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
            "permission": "dashboard:read",
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
            "permission": "audit:read",
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
            "permission": "system:read",
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
            "permission": "profile:read",
            "metrics": [],
        },
    ]


@router.get("/summary")
def portfolio_summary(
    user: User = Depends(require_permission("dashboard:read")),
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
    required = MODULE_PERMISSIONS.get(module_key, "dashboard:read")
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

        locations_total = db.query(func.count(Location.id)).scalar() or 0
        locations_active = (
            db.query(func.count(Location.id)).filter(Location.status == "Active").scalar() or 0
        )
        role_locations_total = db.query(func.count(RoleLocation.id)).scalar() or 0
        presets_total = db.query(func.count(PermissionPreset.id)).scalar() or 0
        presets_active = (
            db.query(func.count(PermissionPreset.id))
            .filter(PermissionPreset.status == "Active")
            .scalar()
            or 0
        )
        preset_applications = (
            db.query(func.coalesce(func.sum(PermissionPreset.times_applied), 0)).scalar() or 0
        )

        kpis = [
            {"label": "Total users", "value": users_total, "context": "All accounts"},
            {"label": "Active users", "value": users_active, "context": "Can sign in"},
            {"label": "Inactive users", "value": users_inactive, "context": "Access revoked"},
            {"label": "Locked accounts", "value": users_locked, "context": "Temporary lockout"},
            {"label": "Locations", "value": f"{locations_active} / {locations_total}", "context": "Active / total"},
            {"label": "Roles / permissions", "value": f"{roles_total} / {permissions_total}", "context": "RBAC catalog"},
            {
                "label": "Permission presets",
                "value": f"{presets_active} / {MAX_PERMISSION_PRESETS}",
                "context": f"{presets_total} saved, {preset_applications} applications",
            },
        ]
        status_rows = (
            db.query(User.status, func.count(User.id)).group_by(User.status).all()
        )
        breakdown = [
            {"label": status, "value": count, "tone": "success" if status == "Active" else "neutral"}
            for status, count in status_rows
        ]
        quick_links = [
            {"label": "User Master", "path": "/users", "permission": "users:read"},
            {"label": "Role Master", "path": "/roles", "permission": "roles:read"},
            {"label": "Location Master", "path": "/locations", "permission": "locations:read"},
            {
                "label": "Permission Presets",
                "path": "/permission-presets",
                "permission": "permission_presets:read",
            },
            {
                "label": "Role Permission Assignment",
                "path": "/role-permissions",
                "all_permissions": ["roles:read", "permissions:read"],
            },
            {
                "label": "Role Location Assignment",
                "path": "/role-locations",
                "all_permissions": ["roles:read", "locations:read"],
            },
            {
                "label": "User Role Assignment",
                "path": "/user-roles",
                "all_permissions": ["users:read", "roles:read"],
            },
            {"label": "Audit Trail", "path": "/audit", "permission": "audit:read"},
        ]
        activity_query = db.query(AuditLog).filter(AuditLog.module_name.in_(USER_MODULES))
    elif module_key == "master-data":
        asset_total = db.query(func.count(Asset.id)).scalar() or 0
        asset_active = (
            db.query(func.count(Asset.id)).filter(Asset.status == "Active").scalar() or 0
        )
        asset_inactive = asset_total - asset_active
        tank_total = db.query(func.count(AssetTank.id)).scalar() or 0
        chart_total = db.query(func.count(AssetCalibrationTable.id)).scalar() or 0
        chart_rows = db.query(func.count(AssetCalibrationRow.id)).scalar() or 0
        calibrated_assets = (
            db.query(func.count(func.distinct(AssetCalibrationTable.asset_id))).scalar() or 0
        )
        local_assets = (
            db.query(func.count(Asset.id)).filter(Asset.asset_scope == "Local").scalar() or 0
        )
        global_assets = (
            db.query(func.count(Asset.id)).filter(Asset.asset_scope == "Global").scalar() or 0
        )

        kpis = [
            {"label": "Total assets", "value": asset_total, "context": f"{asset_active} active"},
            {"label": "Inactive assets", "value": asset_inactive, "context": "Retained for history"},
            {"label": "Tanks declared", "value": tank_total, "context": "Across all assets"},
            {"label": "Calibration charts", "value": chart_total, "context": f"{chart_rows} points"},
            {"label": "Assets calibrated", "value": f"{calibrated_assets} / {asset_total}", "context": "Charts uploaded"},
            {"label": "Local / global", "value": f"{local_assets} / {global_assets}", "context": "By scope"},
        ]

        type_counts = dict(
            db.query(Asset.asset_type_code, func.count(Asset.id)).group_by(Asset.asset_type_code).all()
        )
        # Every fixed asset type is listed, including the ones with no assets
        # yet, so the catalog stays visible and honest about coverage.
        breakdown = [
            {
                "label": definition["name"],
                "value": type_counts.get(definition["code"], 0),
                "tone": "info" if type_counts.get(definition["code"], 0) else "neutral",
            }
            for definition in asset_type_catalog()
        ]
        quick_links = [
            {"label": "Asset Master", "path": "/assets", "permission": "assets:read"},
            {"label": "Location Master", "path": "/locations", "permission": "locations:read"},
        ]
        activity_query = db.query(AuditLog).filter(
            AuditLog.module_name.in_(MASTER_DATA_MODULES)
        )
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
            {"label": "Audit Trail", "path": "/audit", "permission": "audit:read"},
            {"label": "Home", "path": "/", "permission": "dashboard:read"},
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
        quick_links = [{"label": "Audit Trail", "path": "/audit", "permission": "audit:read"}]
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
