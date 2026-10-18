"""Portfolio and module-wise dashboards (owner rule 8)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import (
    get_user_location_ids,
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
    Operation,
    OperationEntry,
    OperationVoyage,
    PasswordResetRequest,
    Permission,
    PermissionPreset,
    PrimeMoverTankerLink,
    Role,
    RoleLocation,
    User,
)
from app.config import MAX_PERMISSION_PRESETS
from app.services.serializers import audit_to_dict, user_to_dict
from app.services.operation_entry_access import scoped_entries
from app.utils.asset_types import PRIME_MOVER, TANKER_TRAILER, asset_type_catalog
from app.utils.operation_types import OPERATION_CATEGORY_CODES, operation_type_catalog
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
    "Prime Mover-Tanker Link",
)

CONFIGURATION_MODULES = (
    "Operation Types",
    "Operation Master",
)

BUSINESS_MODULES = ("Operation Entry",)

TRACKING_MODULES = (
    "Operation Transaction Register",
    "Barge Tracking",
    "Tanker Tracking",
    "Shuttle Tracking",
    "FSO Tracking",
    "Tanker Transaction Report",
)

TRACKING_PERMISSIONS = (
    "operation_transactions:read",
    "barge_tracking:read",
    "tanker_tracking:read",
    "shuttle_tracking:read",
    "fso_tracking:read",
    "tanker_transaction_reports:read",
)

MODULE_PERMISSIONS = {
    "user-management": "users:read",
    "master-data": "assets:read",
    "configurations": "operation_types:read",
    "business": "operation_entries:read",
    # Any one Operation Tracking page grants the module dashboard.
    "operation-tracking": TRACKING_PERMISSIONS,
    "reports": "dashboard:read",
    "backup": "dashboard:read",
    "auditing": "audit:read",
    "system": "system:read",
    "profile": "profile:read",
}


def _scoped_voyages(db: Session, user: User):
    query = db.query(OperationVoyage).filter(
        OperationVoyage.operation_type_code.in_(("SHUTTLE_OPERATIONS", "FSO_OPERATIONS"))
    )
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        query = query.filter(OperationVoyage.location_id.in_(sorted(allowed)))
    return query


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
    active_links = (
        db.query(func.count(PrimeMoverTankerLink.id))
        .filter(PrimeMoverTankerLink.status == "Active")
        .scalar()
        or 0
    )
    active_operations = (
        db.query(func.count(Operation.id)).filter(Operation.status == "Active").scalar() or 0
    )
    entry_total = scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id)).scalar() or 0
    entry_drafts = (
        scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id))
        .filter(OperationEntry.status.in_(["Draft", "Rejected"]))
        .scalar()
        or 0
    )
    entry_submitted = (
        scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id))
        .filter(OperationEntry.status == "Submitted")
        .scalar()
        or 0
    )

    open_convoys = (
        scoped_entries(db, user, party=True)
        .with_entities(func.count(func.distinct(OperationEntry.convoy_number)))
        .filter(
            OperationEntry.operation_type_code == "BARGE_OPERATIONS",
            OperationEntry.status == "Approved",
            ~OperationEntry.convoy_number.in_(
                db.query(OperationVoyage.reference).filter(
                    OperationVoyage.operation_type_code == "BARGE_OPERATIONS",
                    OperationVoyage.status == "CLOSED",
                )
            ),
        )
        .scalar()
        or 0
    )
    open_vessel_voyages = _scoped_voyages(db, user).filter(OperationVoyage.status == "OPEN").count()

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
                "per asset, calibration charts in canonical cm and bbl, and the prime mover to "
                "tanker trailer link register."
            ),
            "path": "/modules/master-data",
            "permission": "assets:read",
            "metrics": [
                {"label": "Assets", "value": asset_total},
                {"label": "Active assets", "value": asset_active},
                {"label": "Tanks", "value": tank_total},
                {"label": "Active links", "value": active_links},
            ],
        },
        {
            "key": "configurations",
            "name": "Configurations",
            "status": "Available",
            "description": (
                "Fixed operation types mapped to asset types, the fixed operation categories "
                "and their stock signs, and the location-scoped Operation Master that feeds "
                "Operation Entry."
            ),
            "path": "/modules/configurations",
            "permission": "operation_types:read",
            "metrics": [
                {"label": "Operation types", "value": len(operation_type_catalog())},
                {"label": "Categories", "value": len(OPERATION_CATEGORY_CODES)},
                {"label": "Active operations", "value": active_operations},
            ],
        },
        {
            "key": "business",
            "name": "Business Operations",
            "status": "Available",
            "description": (
                "Operation Entry for every operation type and asset type on one page, "
                "with fixed module payloads and live quantity calculation. It lists only "
                "editable Draft/Rejected tickets; submission, review, approval, rejection, "
                "recall and cancellation run from the Operation Transaction Register under "
                "Operation Tracking. Stock reconciliation dashboards remain planned."
            ),
            "path": "/modules/business",
            "permission": "operation_entries:read",
            "metrics": [
                {"label": "Operation entries", "value": entry_total},
                {"label": "Editable (Draft/Rejected)", "value": entry_drafts},
                {"label": "Submitted", "value": entry_submitted},
            ],
        },
        {
            "key": "operation-tracking",
            "name": "Operation Tracking",
            "status": "Available",
            "description": (
                "OTMS tracking modules: Operation Transaction Register (submit, review, "
                "approve, reject, recall, cancel), Barge Tracking (receipt, timeline, "
                "load/unload comparison, MTR, close/reopen), Tanker Tracking (receipt "
                "acknowledgement, seal and quantity cross-check, close), Shuttle and FSO "
                "Tracking (voyages, close/reopen, FSO OTR / material balance / outturn) "
                "and the Tanker Transaction Report. Correction requests and the location "
                "accounting-day setting remain planned."
            ),
            "path": "/modules/operation-tracking",
            "permission": None,
            "any_permissions": list(TRACKING_PERMISSIONS),
            "metrics": [
                {"label": "Submitted (awaiting decision)", "value": entry_submitted},
                {"label": "Open barge convoys", "value": open_convoys},
                {"label": "Open shuttle / FSO voyages", "value": open_vessel_voyages},
            ],
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
    options = required if isinstance(required, tuple) else (required,)
    if not is_admin_user(user, db) and not any(user_has_permission(db, user, name) for name in options):
        raise HTTPException(status_code=403, detail="Permission required: " + " or ".join(options))
    return options[0] if len(options) == 1 else " | ".join(options)


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
        prime_mover_active_assets = (
            db.query(func.count(Asset.id))
            .filter(Asset.asset_type_code == PRIME_MOVER, Asset.status == "Active")
            .scalar()
            or 0
        )
        tanker_active_assets = (
            db.query(func.count(Asset.id))
            .filter(Asset.asset_type_code == TANKER_TRAILER, Asset.status == "Active")
            .scalar()
            or 0
        )
        linked_prime_movers = (
            db.query(func.count(func.distinct(PrimeMoverTankerLink.prime_mover_asset_id)))
            .filter(PrimeMoverTankerLink.status == "Active")
            .scalar()
            or 0
        )
        linked_tankers = (
            db.query(func.count(func.distinct(PrimeMoverTankerLink.tanker_asset_id)))
            .filter(PrimeMoverTankerLink.status == "Active")
            .scalar()
            or 0
        )
        link_total = db.query(func.count(PrimeMoverTankerLink.id)).scalar() or 0
        active_links = (
            db.query(func.count(PrimeMoverTankerLink.id))
            .filter(PrimeMoverTankerLink.status == "Active")
            .scalar()
            or 0
        )
        kpis.extend(
            [
                {
                    "label": "Active prime mover links",
                    "value": active_links,
                    "context": f"{link_total} links recorded",
                },
                {
                    "label": "Prime movers without a link",
                    "value": max(prime_mover_active_assets - linked_prime_movers, 0),
                    "context": f"{prime_mover_active_assets} active prime movers",
                },
                {
                    "label": "Tankers without a link",
                    "value": max(tanker_active_assets - linked_tankers, 0),
                    "context": f"{tanker_active_assets} active tanker trailers",
                },
            ]
        )
        quick_links = [
            {"label": "Asset Master", "path": "/assets", "permission": "assets:read"},
            {
                "label": "Prime Mover-Tanker Link",
                "path": "/prime-mover-tanker-links",
                "permission": "prime_mover_tanker_links:read",
            },
            {"label": "Location Master", "path": "/locations", "permission": "locations:read"},
        ]
        activity_query = db.query(AuditLog).filter(
            AuditLog.module_name.in_(MASTER_DATA_MODULES)
        )
    elif module_key == "configurations":
        type_total = len(operation_type_catalog())
        category_total = len(OPERATION_CATEGORY_CODES)
        operation_total = db.query(func.count(Operation.id)).scalar() or 0
        active_operations = (
            db.query(func.count(Operation.id)).filter(Operation.status == "Active").scalar() or 0
        )
        operation_inactive = operation_total - active_operations
        locations_with_operations = (
            db.query(func.count(func.distinct(Operation.location_id))).scalar() or 0
        )
        kpis = [
            {"label": "Operation types", "value": type_total, "context": "Fixed catalogue"},
            {"label": "Categories", "value": category_total, "context": "Each with a stock sign"},
            {
                "label": "Active operations",
                "value": active_operations,
                "context": f"{operation_inactive} inactive",
            },
            {
                "label": "Locations configured",
                "value": locations_with_operations,
                "context": "Locations with at least one operation",
            },
        ]
        type_rows = dict(
            db.query(Operation.operation_type_code, func.count(Operation.id))
            .group_by(Operation.operation_type_code)
            .all()
        )
        breakdown = [
            {
                "label": definition["name"],
                "value": type_rows.get(definition["code"], 0),
                "tone": "info" if type_rows.get(definition["code"], 0) else "neutral",
            }
            for definition in operation_type_catalog()
        ]
        quick_links = [
            {
                "label": "Operation Types",
                "path": "/operation-types",
                "permission": "operation_types:read",
            },
            {"label": "Operation Master", "path": "/operations", "permission": "operations:read"},
            {"label": "Operation References", "path": "/operation-references", "permission": "operation_references:read"},
            {"label": "Location Master", "path": "/locations", "permission": "locations:read"},
        ]
        activity_query = db.query(AuditLog).filter(
            AuditLog.module_name.in_(CONFIGURATION_MODULES)
        )
    elif module_key == "business":
        entry_total = scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id)).scalar() or 0
        entry_drafts = (
            scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id))
            .filter(OperationEntry.status.in_(["Draft", "Rejected"]))
            .scalar()
            or 0
        )
        entry_submitted = (
            scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id))
            .filter(OperationEntry.status == "Submitted")
            .scalar()
            or 0
        )
        entry_today = (
            scoped_entries(db, user, party=True).with_entities(func.count(OperationEntry.id))
            .filter(OperationEntry.created_at >= today_start)
            .scalar()
            or 0
        )
        kpis = [
            {"label": "Operation entries", "value": entry_total, "context": "All tickets"},
            {"label": "Editable", "value": entry_drafts, "context": "Draft and Rejected"},
            {"label": "Submitted", "value": entry_submitted, "context": "Awaiting decision"},
            {"label": "Created today", "value": entry_today, "context": "Since midnight UTC"},
        ]
        status_rows = (
            scoped_entries(db, user, party=True).with_entities(OperationEntry.status, func.count(OperationEntry.id))
            .group_by(OperationEntry.status)
            .all()
        )
        tone_by_status = {
            "Draft": "info",
            "Submitted": "warning",
            "Approved": "success",
            "Rejected": "danger",
            "Cancelled": "neutral",
        }
        breakdown = [
            {
                "label": status,
                "value": count,
                "tone": tone_by_status.get(status, "neutral"),
            }
            for status, count in status_rows
        ]
        quick_links = [
            {
                "label": "Operation Entry",
                "path": "/operation-entry",
                "permission": "operation_entries:read",
            },
            {"label": "Operation Master", "path": "/operations", "permission": "operations:read"},
            {"label": "Asset Calibration", "path": "/asset-calibration", "permission": "assets:read"},
            {"label": "Operation References", "path": "/operation-references", "permission": "operation_references:read"},
        ]
        activity_query = db.query(AuditLog).filter(
            AuditLog.module_name.in_(BUSINESS_MODULES),
            AuditLog.entity_id.in_(scoped_entries(db, user, party=True).with_entities(OperationEntry.id)),
        )
    elif module_key == "operation-tracking":
        scoped = scoped_entries(db, user, party=True)
        count = lambda query: query.with_entities(func.count(OperationEntry.id)).scalar() or 0
        barge_closed = db.query(OperationVoyage.reference).filter(
            OperationVoyage.operation_type_code == "BARGE_OPERATIONS", OperationVoyage.status == "CLOSED"
        )
        approved_barge = scoped.filter(
            OperationEntry.operation_type_code == "BARGE_OPERATIONS", OperationEntry.status == "Approved"
        )
        kpis = [
            {"label": "Submitted", "value": count(scoped.filter(OperationEntry.status == "Submitted")), "context": "Awaiting approve / reject"},
            {"label": "Approved today", "value": count(scoped.filter(OperationEntry.approved_at >= today_start)), "context": "Since midnight UTC"},
            {
                "label": "Open barge convoys",
                "value": approved_barge.filter(~OperationEntry.convoy_number.in_(barge_closed))
                .with_entities(func.count(func.distinct(OperationEntry.convoy_number))).scalar() or 0,
                "context": "Approved tickets, not closed",
            },
            {
                "label": "Open shuttle / FSO voyages",
                "value": _scoped_voyages(db, user).filter(OperationVoyage.status == "OPEN").count(),
                "context": "Voyage status OPEN",
            },
        ]
        breakdown = [
            {"label": status, "value": count(scoped.filter(OperationEntry.status == status)), "tone": tone}
            for status, tone in (("Draft", "info"), ("Submitted", "warning"), ("Approved", "success"), ("Rejected", "danger"), ("Cancelled", "neutral"))
        ]
        quick_links = [
            {"label": "Operation Transaction Register", "path": "/operation-transactions", "permission": "operation_transactions:read"},
            {"label": "Barge Tracking", "path": "/barge-tracking", "permission": "barge_tracking:read"},
            {"label": "Tanker Tracking", "path": "/tanker-tracking", "permission": "tanker_tracking:read"},
            {"label": "Shuttle Tracking", "path": "/shuttle-tracking", "permission": "shuttle_tracking:read"},
            {"label": "FSO Tracking", "path": "/fso-tracking", "permission": "fso_tracking:read"},
            {"label": "Tanker Transaction Report", "path": "/tanker-transaction-report", "permission": "tanker_transaction_reports:read"},
        ]
        activity_query = db.query(AuditLog).filter(AuditLog.module_name.in_(TRACKING_MODULES))
        if get_user_location_ids(db, user) is not None:
            # Location-scoped users only see their own tracking activity here.
            activity_query = activity_query.filter(AuditLog.actor_user_id == user.id)
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
