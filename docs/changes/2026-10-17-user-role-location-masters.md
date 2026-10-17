# User, Role and Location Master Modules — 2026-10-17

## Summary

Completed the requested User Master additions and brought the Role Master and Location Master
workflow into HCA System. Added Role Permission, Role Location and User Role assignment modules
using HCA's existing application structure and typed relational data. The Costing
`resource:action` permission approach and the OTMS master/assignment workflows were used as the
named references; no other reference repositories were used.

## Delivered

### User and Role Master

- User Master now supports create, edit, soft-deactivation, role changes, administrator password
  reset, import preview/commit and CSV/XLSX/PDF export, with search, filters, pagination and
  audited actions.
- Role Master supports configurable role CRUD, soft-deactivation, search/status/date filters,
  import preview/commit and CSV/XLSX/PDF export.
- Reserved Admin protections prevent assignment or modification through ordinary master and
  assignment workflows. Non-admin actors cannot grant user roles or role permissions beyond the
  standard permissions they themselves hold.

### Location Master and assignments

- Added typed `locations` records with unique codes, location types, optional self-referencing
  parents, active/inactive status and hierarchy-cycle validation.
- Location Master supports CRUD, parent/child safeguards, filters, pagination, bounded CSV/XLSX
  import preview/commit and CSV/XLSX/PDF export.
- Role Permission, Role Location and User Role pages provide filtered/paginated assignment lists,
  standard multi-select replacement controls, CSV/XLSX/PDF exports and preview-before-commit
  CSV/XLSX imports. Import cells use semicolon-separated values for multiple permissions,
  location codes or role names. Every file is validated before any assignment is replaced.
- Assignment changes and import/export events are audited. Role/location and user/role links use
  typed association records, not JSON or serialized arrays.

### Standard permissions and startup behavior

- Registered standard `resource:action` permission definitions in
  `backend/app/utils/default_permissions.py`. Startup bootstrap creates/refreshes catalog rows
  idempotently and migrates known title-based legacy grants to standard keys before deactivating
  legacy rows.
- CRUD pages use `<resource>:read`, `:create`, `:update` and `:delete`; assignment writes use
  `assignments:write`. Imports use the resource's standard `:create` capability; exports use
  `:read`. No new title-based CRUD permissions were introduced.
- Converted dashboard, profile/security, audit, security-event and system-health gates to
  standard resource capabilities too. Bootstrap migrates their former title-based grants and
  deactivates the old rows.
- Updated `docs/memory/PROJECT_MEMORY.md` Rule 11 so future pages register standard permissions
  in `RESOURCE_PERMISSION_DEFINITIONS` before UI/API implementation; startup provisioning is
  automatic and idempotent.

## Verification

- `cd backend && ./.venv/bin/python -m pytest -q` → **26 passed, 1 warning** (Starlette/AnyIO
  deprecation warning).
- `cd frontend && npm ci` → **success, 0 reported vulnerabilities**.
- `cd frontend && npm run build` → **success** (Vite 8.3.4).
- `python -m compileall -q app tests` → **success**.
- Manual browser smoke tests, PostgreSQL deployment-schema verification and light/dark visual
  review have not been run.

## Important implementation files

- Backend: `backend/app/routers/users.py`, `roles.py`, `locations.py`, `role_locations.py`,
  `user_roles.py`, `backend/app/services/master_import.py`,
  `backend/app/utils/default_permissions.py`, `backend/app/services/bootstrap.py`.
- Frontend: `frontend/src/pages/Users.jsx`, `Roles.jsx`, `Locations.jsx`, `RolePermissions.jsx`,
  `RoleLocations.jsx`, `UserRoles.jsx` and corresponding API clients/dialogs.
- Tests: `backend/tests/test_master_data_rbac.py` and the updated
  `backend/tests/test_rbac_and_audit.py`.

## Remaining work

Additional reference masters (asset types, assets, tanks/vessels and operation types),
PostgreSQL deployment-schema verification, manual browser/light-dark review, an Alembic baseline,
and the planned business, report, backup and audit-retention modules remain outside this delivery.
