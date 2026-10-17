"""Standard permission catalog (owner rule 11).

The catalog is the single source of truth for:
  * startup seeding (``seed_permission_catalog``),
  * the standalone administrator seed,
  * ``GET /api/permissions/catalog`` which powers the RBAC matrix.

Permissions are grouped module-wise, mirroring the top navigation. Naming is
``View|Create|Edit|Delete <Entity>`` plus explicit workflow verbs. This module
must stay free of database/application imports so the standalone seed script
can use it safely.
"""

from __future__ import annotations

VIEW = "View"
CREATE = "Create"
EDIT = "Edit"
DELETE = "Delete"
OTHER = "Other"

ACTION_ORDER = [VIEW, CREATE, EDIT, DELETE, OTHER]


def _perm(permission_name: str, action: str, description: str) -> dict:
    return {
        "permission_name": permission_name,
        "action": action,
        "description": description,
    }


def _crud(entity: str, label: str | None = None, actions=(VIEW, CREATE, EDIT, DELETE)) -> list[dict]:
    noun = label or f"{entity.lower()} records"
    templates = {
        VIEW: f"Can view {noun}",
        CREATE: f"Can create {noun}",
        EDIT: f"Can edit {noun}",
        DELETE: f"Can delete {noun}",
    }
    return [_perm(f"{action} {entity}", action, templates[action]) for action in actions]


PERMISSION_CATALOG = [
    {
        "category": "Home",
        "modules": [
            {
                "module_name": "Portfolio Dashboard",
                "permissions": [
                    _perm("View System Dashboard", VIEW, "Can view the portfolio dashboard"),
                ],
            },
        ],
    },
    {
        "category": "User Management",
        "modules": [
            {
                "module_name": "User Master",
                "permissions": _crud("User", "users")
                + [_perm("Export User", OTHER, "Can export user records")],
            },
            {
                "module_name": "Role Master",
                "permissions": _crud("Role", "roles"),
            },
            {
                "module_name": "Permission Master",
                "permissions": _crud("Permission", "permissions"),
            },
            {
                "module_name": "Role Permission Assignment",
                "permissions": [
                    _perm(
                        "View Role Permission Assignment",
                        VIEW,
                        "Can view role permission assignments",
                    ),
                    _perm(
                        "Edit Role Permission Assignment",
                        EDIT,
                        "Can assign and remove permissions for roles",
                    ),
                ],
            },
            {
                "module_name": "User Role Assignment",
                "permissions": [
                    _perm(
                        "View User Role Assignment",
                        VIEW,
                        "Can view user role assignments",
                    ),
                    _perm(
                        "Edit User Role Assignment",
                        EDIT,
                        "Can assign and remove roles for users",
                    ),
                ],
            },
            {
                "module_name": "Profile & Security",
                "permissions": [
                    _perm(
                        "View Own Security Settings",
                        VIEW,
                        "Can view own profile and security settings",
                    ),
                    _perm(
                        "Edit Own Security Settings",
                        EDIT,
                        "Can change own password and two-factor settings",
                    ),
                ],
            },
            {
                "module_name": "User Management Dashboard",
                "permissions": [
                    _perm(
                        "View User Management Dashboard",
                        VIEW,
                        "Can view the User Management module dashboard",
                    ),
                ],
            },
        ],
    },
    {
        "category": "Auditing Modules",
        "modules": [
            {
                "module_name": "Audit Trail",
                "permissions": [
                    _perm("View Audit Log", VIEW, "Can view the audit trail"),
                    _perm("Export Audit Log", OTHER, "Can export audit trail records"),
                ],
            },
            {
                "module_name": "Security Events",
                "permissions": [
                    _perm("View Security Events", VIEW, "Can view authentication and security events"),
                ],
            },
            {
                "module_name": "Auditing Dashboard",
                "permissions": [
                    _perm(
                        "View Auditing Dashboard",
                        VIEW,
                        "Can view the Auditing module dashboard",
                    ),
                ],
            },
        ],
    },
    {
        "category": "System",
        "modules": [
            {
                "module_name": "System Administration",
                "permissions": [
                    _perm("View System Health", VIEW, "Can view system health and seed status"),
                ],
            },
        ],
    },
]


def iter_catalog_entries():
    """Yield one dict per permission with category/module attached."""
    for category in PERMISSION_CATALOG:
        category_name = category["category"]
        for module in category["modules"]:
            module_name = module["module_name"]
            for permission in module["permissions"]:
                yield {
                    "permission_name": permission["permission_name"],
                    "module_name": module_name,
                    "category": category_name,
                    "action": permission["action"],
                    "description": permission["description"],
                }


STANDARD_PERMISSIONS = list(iter_catalog_entries())
STANDARD_PERMISSION_NAMES = [entry["permission_name"] for entry in STANDARD_PERMISSIONS]
