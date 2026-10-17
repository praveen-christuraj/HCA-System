# HCA System — Module Map and Status

> Honest status board. **Never describe a Planned module as shipped.**
> Updated whenever a module is added, partially delivered or completed.
> Last updated: 2026-10-17 (permission preset delivery)

---

## 1. Module map

| Module | Purpose | Status |
| --- | --- | --- |
| **Home / Portfolio** | Cross-module KPIs, module status, recent audited activity | **Delivered (v0.1)** |
| **User Management** | User Master, Role Master, Location Master, Permission Presets, Role Permission, Role Location, User Role assignment, profile and security | **Core identity, location access and RBAC delivered and verified:** user/role/location CRUD, imports/exports, permission assignments, capped named permission presets applied to roles in replace/add mode, role-location assignments, user-role assignments, reserved-Admin protections. Profile/security baseline remains available; further security administration is planned. |
| **Master Data Management** | Asset Master over seven hard-coded asset types, tanks declared per asset, Asset Calibration with fixed three-column charts and dip-to-volume interpolation | **Asset Master and Asset Calibration delivered and verified:** fixed asset type catalog, Local/Global scoping, typed tanks, chart upload in cm/mm/m and L/kL/bbl converted to canonical cm/bbl, 2D and 3D interpolation, exports and full audit. Operation types, report profiles and flowmeter configuration remain planned. |
| **Business / Operations** | Operation entry, transactions, workflow, tank/vessel operations, export operations, tracking | **Planned (OTMS extraction)** |
| **Report Modules** | Tank stock ledger, out-turn, material balance, tanker transaction, tracking reports | **Planned (OTMS extraction)** |
| **Back-up Modules** | Backup settings, backup jobs, restore requests and validation | **Planned (OTMS extraction)** |
| **Auditing Modules** | Audit trail, security events, UI activity, module audit dashboard | **Delivered (v0.1):** audit trail with filters, pagination and CSV/XLSX/PDF export; module dashboard. Security-event view and archive/purge remain planned. |
| **System / Administration** | Health, seed status, application settings, notifications | **Foundation delivered:** health and seed status. Settings/notifications remain planned. |

## 2. What the current delivery implements

### Backend

- HCA FastAPI + SQLAlchemy application, JWT auth, TOTP login challenge, password-reset request,
  account lockout, standard RBAC enforcement and typed audit trail with middleware fallback.
- Idempotent `resource:action` permission catalog provisioning and migration of known legacy
  permission grants. Assignment mutations use the shared `assignments:write` capability.
- User Master create/update, soft-deactivation, password reset, user-role changes, import
  preview/commit and CSV/XLSX/PDF export, with permission-subset and reserved-Admin safeguards.
- Role Master search/status/date filters, CRUD with soft-deactivation, import/export and standard
  Role Permission read/replace endpoints.
- Permission Presets (`permission_presets` + `permission_preset_items`) store up to 20 named,
  reusable permission sets (`MAX_PERMISSION_PRESETS`). Presets support CRUD with soft deactivation,
  permanent delete only while never applied, filtered/paginated listing, CSV/XLSX import
  preview/commit with per-row cap reporting, CSV/XLSX/PDF export, and `POST /{id}/apply` which
  copies the preset into `role_permissions` for 1–200 roles in `replace` or `add` mode after
  validating every role. Applying requires `permission_presets:read` **and** `assignments:write`,
  refuses the reserved Admin role, inactive roles and inactive presets, and enforces the
  "no grants outside your own access" rule for non-administrators.
- Location Master uses typed location and parent columns, validates parent cycles, supports
  create/update/soft-deactivation, bounded CSV/XLSX import preview/commit and filtered exports.
- Role Permission, Role Location and User Role assignment APIs support filtered/paginated lists,
  CSV/XLSX/PDF exports, audited replacement and bounded CSV/XLSX preview/commit imports. Each
  assignment import validates the complete file before replacing any row; the reserved Admin
  role/account cannot be modified through these assignment modules.
- Shared master import parser caps files at 5,000 data rows. Role permissions accept
  `role_name,permission_names`; role locations accept `role_name,location_codes`; user roles
  accept `username,role_names`. Multi-value cells use semicolon-separated standard keys/names.
- Asset Master registers assets against the seven hard-coded asset types
  (`app/utils/asset_types.py`), with `Local`/`Global` scope, a typed `asset_tanks` child table
  declared in the same request, a `calibration_required` flag, filtered/paginated list,
  CSV/XLSX import preview/commit and CSV/XLSX/PDF export. Non-admin users see global assets plus
  assets in their assigned locations.
- Asset Calibration stores one active three-column chart per asset in typed `Numeric` columns in
  canonical cm and bbl (`app/services/calibration_import.py`), accepts cm/mm/m and L/kL/bbl
  source units plus long and wide upload layouts, and exposes single and batch dip-to-volume
  lookup through `app/services/calibration_engine.py` (2D within a tank, 3D across the asset's
  tanks by exact tank name).
- Master Data dashboard KPIs (assets, tanks, charts, per-type breakdown over all seven fixed
  types) and quick links are live and permission-filtered.

### Frontend

- Authenticated shell, top permission-filtered navigation, portfolio dashboard, module dashboards
  and audit trail.
- User Master create/edit dialogs, password reset, role assignment controls, import preview and
  audited export.
- Role Master and Location Master pages with pagination, search/advanced filters, independent
  date groups, import preview, three-format export, add/edit and soft-deactivation.
- Role Permission, Role Location and User Role assignment pages with standard permission gating,
  multi-select controls, server pagination, filters, CSV/XLSX preview-and-confirm import,
  three-format export and UI audit logging.
- Permission Presets page with the slot indicator, grouped permission picker (module select-all,
  live counter, "load permissions from a role"), apply dialog with replace/add mode cards and a
  searchable eligible-role list, import preview and three-format export. Role Permission Assignment
  carries a preset bar that previews the exact delta, stages replace/add for review before the
  audited save, and can store the current selection as a new preset.
- Asset Master page with the hard-coded asset type dropdown, scope-aware location field, tank
  sub-editor, filters, import preview and three-format export.
- Asset Calibration page with chart coverage per tank, upload dialog (basis, units, preview with
  per-row validation and conversion columns), three-format export and a dip-to-volume calculator
  that shows the method and bracketing points of every resolved reading.
- Navy/white design system with light/dark/system theme support; no new side navigation or
  non-standard CRUD permissions.

### Deployment and schema

- Docker Compose remains PostgreSQL + FastAPI + nginx-served React; the cloud API deploy remains
  native Python on Render. SQLAlchemy `create_all` creates the Location, RoleLocation, Asset,
  AssetTank, AssetCalibrationTable, AssetCalibrationRow, PermissionPreset and
  PermissionPresetItem tables at startup; no Alembic baseline has been introduced yet. The
  permission catalog grows from 26 to 30 rows with the `permission_presets` resource.

## 3. Verification state and remaining work

- Backend: `cd backend && ./.venv/bin/python -m pytest -q` → **80 passed, 1 warning**. Coverage
  includes the master/assignment APIs, import preview and commit, hierarchy checks, Admin guards,
  standard permission enforcement, legacy grant migration, the hard-coded asset type catalog,
  unit conversion factors, chart validation, 2D/3D interpolation, and the permission preset cap,
  apply modes, apply guards and preset RBAC.
- Frontend: `cd frontend && npm run build` → **success** (Vite 8.3.4 production build, 68 modules).
- Dependency install: `cd frontend && npm ci` → **success, 0 reported vulnerabilities**.
- Live HTTP smoke tests through uvicorn and the Vite proxy → **36/36 checks** for the asset and
  calibration path and **78/78 checks** for the permission preset path (both end to end).
- A temporary jsdom harness rendered the real preset components and the updated assignment page
  against a stubbed API → **58/58 DOM checks** (harness not committed).
- Manual browser smoke tests, PostgreSQL deployment-schema verification and light/dark visual
  review of the new pages have **not** been run in this delivery (no browser binary is installable
  in the sandbox; the new tables were instead compiled through the PostgreSQL dialect). An XLSX
  wide-sheet calibration upload against a real Excel file has **not** been exercised (CSV wide
  layout has).
- Profile & Security enhancements, an Alembic migration baseline, operation type/report profile
  masters, business operations, reports, backup, audit archive/retention and security-event
  dashboard remain planned.
