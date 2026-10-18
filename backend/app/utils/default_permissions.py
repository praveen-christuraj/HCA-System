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
        # Named, reusable permission sets (capped at MAX_PERMISSION_PRESETS)
        # that are applied to roles instead of ticking permissions one by one.
        # Applying a preset to a role is an assignment write and additionally
        # requires the shared ``assignments:write`` capability.
        "resource": "permission_presets",
        "module_name": "Permission Presets",
        "category": "User Management",
        "label": "reusable permission presets",
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
        "category": "User Management",
        "label": "locations",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "assets",
        "module_name": "Asset Master",
        "category": "Master Data Management",
        "label": "assets, their tanks and calibration charts",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        # Prime Mover-Tanker Link: which tanker trailer each prime mover hauls,
        # and for which dates. Edit covers closing a link.
        "resource": "prime_mover_tanker_links",
        "module_name": "Prime Mover-Tanker Link",
        "category": "Master Data Management",
        "label": "prime mover to tanker trailer links",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "asset_assignments",
        "module_name": "Asset Assignment",
        "category": "Master Data Management",
        "label": "asset assignments to users, locations and external parties",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        # Hard-coded operation types and categories. Read-only: the catalogue
        # is fixed by the system, so there is no create, update or delete.
        "resource": "operation_types",
        "module_name": "Operation Types",
        "category": "Configurations",
        "label": "the fixed operation types and operation categories",
        "actions": (READ,),
    },
    {
        # Location-scoped operations under the fixed types and categories.
        # These populate the Operation Entry dropdowns.
        "resource": "operations",
        "module_name": "Operation Master",
        "category": "Configurations",
        "label": "location operations",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "location_operation_availability",
        "module_name": "Location Operation Availability",
        "category": "Configurations",
        "label": "location operation availability mappings",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "location_accounting_day_settings",
        "module_name": "Location Accounting Day Setting",
        "category": "Configurations",
        "label": "location accounting day start/end settings",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "company_report_profiles",
        "module_name": "Company Report Profiles",
        "category": "Configurations",
        "label": "company report branding and header/footer profiles",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "material_balance_templates",
        "module_name": "Material Balance Template Master",
        "category": "Configurations",
        "label": "material balance report templates and columns",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        # Business: Operation Entry tickets for every operation type and asset
        # type on one page. Create covers saving Draft tickets;
        # update covers edits; submissions/reviews/approvals are separate resources. Delete is
        # the OTMS "Cancel" of a Draft/Rejected ticket (the row is kept).
        "resource": "operation_entries",
        "module_name": "Operation Entry",
        "category": "Business Modules",
        "label": "operation entry tickets",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "operation_submissions", "module_name": "Ticket Submission",
        "category": "Business Modules", "label": "ticket submission",
        "actions": (READ, CREATE, DELETE,),
    },
    {
        "resource": "operation_reviews", "module_name": "Ticket Review",
        "category": "Business Modules", "label": "ticket review",
        "actions": (CREATE,),
    },
    {
        "resource": "operation_approvals", "module_name": "Ticket Approval",
        "category": "Business Modules", "label": "ticket approval",
        "actions": (CREATE, UPDATE,),
    },
    {
        "resource": "receiving_tickets", "module_name": "Receiving Tickets",
        "category": "Business Modules", "label": "receiving tickets",
        "actions": (CREATE,),
    },
    {
        "resource": "operation_references", "module_name": "Operation References",
        "category": "Business Modules", "label": "operation references",
        "actions": (READ, CREATE, UPDATE, DELETE,),
    },
    {
        "resource": "operation_policies", "module_name": "Operation Workflow Policies",
        "category": "Business Modules", "label": "operation workflow policies",
        "actions": (READ, CREATE, UPDATE, DELETE,),
    },
    {
        "resource": "operation_voyages", "module_name": "Operation Voyages",
        "category": "Business Modules", "label": "operation voyages",
        "actions": (READ, UPDATE,),
    },
    {
        "resource": "flowmeter_records", "module_name": "Flowmeter Records",
        "category": "Business Modules", "label": "standalone flowmeter record entries",
        "actions": (READ, CREATE, UPDATE, DELETE,),
    },
    {
        "resource": "movement_mappings", "module_name": "Movement Mapping",
        "category": "Business Modules", "label": "sender and receiver movement mappings",
        "actions": (READ, CREATE, UPDATE, DELETE,),
    },
    {
        "resource": "operation_tasks", "module_name": "Operation Task Manager",
        "category": "Business Modules", "label": "operation approval and correction tasks",
        "actions": (READ, CREATE, UPDATE,),
    },
    {
        "resource": "correction_requests", "module_name": "Approved Transaction Corrections",
        "category": "Business Modules", "label": "approved transaction correction and revoke requests",
        "actions": (READ, CREATE, UPDATE,),
    },
    {
        "resource": "export_operations", "module_name": "Export Operations",
        "category": "Export Operations", "label": "export permits, blocks, entities, consignees and transactions",
        "actions": (READ, CREATE, UPDATE, DELETE,),
    },
    # Operation Tracking (OTMS tracking modules). Status workflow actions on a
    # ticket keep their existing capabilities (operation_submissions /
    # operation_reviews / operation_approvals / operation_entries:delete); these
    # resources only gate the register and tracking pages and their own facts.
    {
        "resource": "operation_transactions", "module_name": "Operation Transaction Register",
        "category": "Operation Tracking", "label": "the operation transaction register and ticket detail",
        "actions": (READ,),
    },
    {
        # update = Fix Barge Timeline (event-type correction) and acknowledging /
        # revoking barge receipts without a separate shipment-receipt grant.
        "resource": "barge_tracking", "module_name": "Barge Tracking",
        "category": "Operation Tracking", "label": "barge tracking",
        "actions": (READ, UPDATE,),
    },
    {
        # update = acknowledge / revoke receipt and close a tanker movement.
        "resource": "tanker_tracking", "module_name": "Tanker Tracking",
        "category": "Operation Tracking", "label": "tanker tracking",
        "actions": (READ, UPDATE,),
    },
    {
        "resource": "shuttle_tracking", "module_name": "Shuttle Tracking",
        "category": "Operation Tracking", "label": "shuttle tracking",
        "actions": (READ,),
    },
    {
        "resource": "fso_tracking", "module_name": "FSO Tracking",
        "category": "Operation Tracking", "label": "FSO tracking and FSO reports",
        "actions": (READ,),
    },
    {
        "resource": "tanker_transaction_reports", "module_name": "Tanker Transaction Report",
        "category": "Operation Tracking", "label": "the tanker transaction report",
        "actions": (READ,),
    },
    {
        # OTMS "Acknowledge Shipment Receipt": create = acknowledge a barge or
        # tanker receipt, delete = revoke an acknowledgement.
        "resource": "shipment_receipts", "module_name": "Shipment Receipts",
        "category": "Operation Tracking", "label": "barge and tanker receipt acknowledgements",
        "actions": (CREATE, DELETE,),
    },
    {
        "resource": "reports",
        "module_name": "Operational Reports",
        "category": "Reporting",
        "label": "tank operation summary, out-turn summary, material balance and stock ledger reports",
        "actions": (READ, UPDATE),
    },
    {
        "resource": "backup_recovery",
        "module_name": "Backup & Recovery",
        "category": "Back-up & Recovery",
        "label": "database backups, restore requests and restore validations",
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
    {
        "resource": "system_notifications",
        "module_name": "System Notifications",
        "category": "System",
        "label": "system-wide notifications, banners and delivery receipts",
        "actions": (READ, CREATE, UPDATE, DELETE),
    },
    {
        "resource": "database_browser",
        "module_name": "Database Browser",
        "category": "System",
        "label": "the read-only database table browser",
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
