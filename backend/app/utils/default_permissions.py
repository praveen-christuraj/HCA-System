"""Standard permission catalog (owner rule 11).

The permission model follows Costing's ``resource:action`` capability keys.
Every page backed by a standard resource is registered in
``RESOURCE_PERMISSION_DEFINITIONS``; startup seeding creates those permissions
idempotently and grants the active catalog to the reserved Admin role.

Use only the standard actions ``read``, ``create``, ``update`` and ``delete``
for page resources. Cross-page assignment writes share Costing's standard
``assignments:write`` capability. Export uses ``read`` and import uses
``create``; do not introduce page-specific Export/Import permission names.

Dashboard, profile, audit, security and system pages are also registered as
standard resources. Known title-based grants are migrated to these standard
keys before the old catalog rows are deactivated. This module stays free of
database/application imports so it can be used by the standalone seed script.
"""

from __future__ import annotations

READ = "read"
CREATE = "create"
UPDATE = "update"
DELETE = "delete"
WRITE = "write"

ACTION_ORDER = [READ, CREATE, UPDATE, DELETE, WRITE]

# Costing-style standard capabilities, keyed by the API/UI resource.
# User Master intentionally has no delete action: account removal is a
# soft-deactivation governed by users:update, matching Costing's user model.
RESOURCE_PERMISSION_DEFINITIONS = [
    {
        "resource": "dashboard",
        "module_name": "Portfolio Dashboard",
        "category": "Home",
        "label": "the portfolio dashboard",
        "actions": (READ,),
    },
    {
        "resource": "users",
        "module_name": "User Master",
        "category": "User Management",
        "label": "user accounts",
        "actions": (READ, CREATE, UPDATE),
    },
    {
        "resource": "roles",
        "module_name": "Role Master",
        "category": "User Management",
        "label": "roles",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "permissions",
        "module_name": "Permission Master",
        "category": "User Management",
        "label": "permissions",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "assignments",
        "module_name": "Assignments",
        "category": "User Management",
        "label": "role and user assignments",
        "actions": (WRITE,),
    },
    {
        "resource": "profile",
        "module_name": "Profile & Security",
        "category": "User Management",
        "label": "own profile and security settings",
        "actions": (READ, UPDATE),
    },
    {
        "resource": "locations",
        "module_name": "Location Master",
        "category": "Master Data Management",
        "label": "locations",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "audit",
        "module_name": "Audit Trail",
        "category": "Auditing Modules",
        "label": "audit records",
        "actions": (READ,),
    },
    {
        "resource": "security",
        "module_name": "Security Events",
        "category": "Auditing Modules",
        "label": "security events",
        "actions": (READ,),
    },
    {
        "resource": "system",
        "module_name": "System Administration",
        "category": "System",
        "label": "system health and seed status",
        "actions": (READ,),
    },
]

RESOURCE_CAPABILITIES = {
    definition["resource"]: definition["actions"]
    for definition in RESOURCE_PERMISSION_DEFINITIONS
}

STANDARD_RESOURCE_ACTIONS = (READ, CREATE, UPDATE, DELETE)


def _resource_permission_entries(definition: dict) -> list[dict]:
    resource = definition["resource"]
    module_name = definition["module_name"]
    category = definition["category"]
    label = definition["label"]
    entries = []
    for action in definition["actions"]:
        verb = {
            READ: "Read",
            CREATE: "Create",
            UPDATE: "Update",
            DELETE: "Delete",
            WRITE: "Write",
        }[action]
        entries.append(
            {
                "permission_name": f"{resource}:{action}",
                "module_name": module_name,
                "category": category,
                "action": action,
                "description": f"Can {verb.lower()} {label}",
            }
        )
    return entries


def _build_catalog() -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []

    for definition in RESOURCE_PERMISSION_DEFINITIONS:
        key = (definition["category"], definition["module_name"])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].extend(_resource_permission_entries(definition))

    categories: list[dict] = []
    for category_name, module_name in order:
        if not categories or categories[-1]["category"] != category_name:
            categories.append({"category": category_name, "modules": []})
        categories[-1]["modules"].append(
            {"module_name": module_name, "permissions": grouped[(category_name, module_name)]}
        )
    return categories


PERMISSION_CATALOG = _build_catalog()


def iter_catalog_entries():
    """Yield one dictionary per catalog permission with module metadata."""
    for category in PERMISSION_CATALOG:
        for module in category["modules"]:
            for permission in module["permissions"]:
                yield {
                    "permission_name": permission["permission_name"],
                    "module_name": module["module_name"],
                    "category": category["category"],
                    "action": permission["action"],
                    "description": permission["description"],
                }


STANDARD_PERMISSIONS = list(iter_catalog_entries())
STANDARD_PERMISSION_NAMES = [entry["permission_name"] for entry in STANDARD_PERMISSIONS]

# One-time, idempotent grants that preserve existing roles when migrating from
# the HCA title-based catalog to Costing's resource:action keys. The old rows
# are deactivated after their grants have been translated.
LEGACY_PERMISSION_MIGRATIONS = {
    "View User": ("users:read",),
    "Create User": ("users:create",),
    "Edit User": ("users:update",),
    "Delete User": ("users:update",),
    "Export User": ("users:read",),
    "View Role": ("roles:read",),
    "Create Role": ("roles:create",),
    "Edit Role": ("roles:update",),
    "Delete Role": ("roles:delete",),
    "View Permission": ("permissions:read",),
    "Create Permission": ("permissions:create",),
    "Edit Permission": ("permissions:update",),
    "Delete Permission": ("permissions:delete",),
    "View Location": ("locations:read",),
    "Create Location": ("locations:create",),
    "Edit Location": ("locations:update",),
    "Delete Location": ("locations:delete",),
    "View Role Permission Assignment": ("roles:read", "permissions:read"),
    "Edit Role Permission Assignment": ("assignments:write",),
    "View User Role Assignment": ("users:read", "roles:read"),
    "Edit User Role Assignment": ("assignments:write",),
    "View Role Location Assignment": ("roles:read", "locations:read"),
    "Edit Role Location Assignment": ("assignments:write",),
    "View System Dashboard": ("dashboard:read",),
    "View User Management Dashboard": ("users:read",),
    "View Own Security Settings": ("profile:read",),
    "Edit Own Security Settings": ("profile:update",),
    "View Audit Log": ("audit:read",),
    "Export Audit Log": ("audit:read",),
    "View Security Events": ("security:read",),
    "View Auditing Dashboard": ("audit:read",),
    "View System Health": ("system:read",),
}
