# HCA System — Module Map and Status

> Honest status board. **Never describe a Planned module as shipped.**
> Updated whenever a module is added, partially delivered or completed.
> Last updated: 2026-10-17 (Prime Mover-Tanker Link and Configurations delivery)

---

## 1. Module map

| Module | Purpose | Status |
| --- | --- | --- |
| **Home / Portfolio** | Cross-module KPIs, module status, recent audited activity | **Delivered (v0.1)** |
| **User Management** | User Master, Role Master, Location Master, Permission Presets, Role Permission, Role Location, User Role assignment, profile and security | **Core identity, location access and RBAC delivered and verified:** user/role/location CRUD, imports/exports, permission assignments, capped named permission presets applied to roles in replace/add mode, role-location assignments, user-role assignments, reserved-Admin protections. Profile/security baseline remains available; further security administration is planned. |
| **Master Data Management** | Asset Master over seven hard-coded asset types, tanks declared per asset, Asset Calibration with fixed three-column charts and dip-to-volume interpolation, Prime Mover-Tanker Link | **Asset Master, Asset Calibration and Prime Mover-Tanker Link delivered and verified:** fixed asset type catalog, Local/Global scoping, typed tanks, chart upload in cm/mm/m and L/kL/bbl converted to canonical cm/bbl, 2D and 3D interpolation, exports and full audit. The link pairs one prime mover with one tanker trailer, allows one Active link per asset, and supports close, import and export. Report profiles and flowmeter configuration remain planned. |
| **Configurations** | Fixed Operation Types mapped to asset types, the fixed operation categories with their stock signs, and the location-scoped Operation Master that feeds Operation Entry | **Operation Types and Operation Master delivered and verified:** hard-coded catalogue (ADR-019), read-only type and category pages, location-scoped operations with derived sign, unique code and name per location and type, deactivation, import, export and dashboard. OTMS Tracking Module Configuration is out of scope for now. Operation Entry waits for owner confirmation. |
| **Business / Operations** | Operation entry, transactions, workflow, tank/vessel operations, export operations, tracking | **Planned (OTMS extraction).** Operation Entry is next, after owner confirmation. |
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
  types, active links) and quick links are live and permission-filtered.
- Prime Mover-Tanker Link (`/api/prime-mover-tanker-links`) pairs a `PRIME_MOVER` asset with a
  `TANKER_TRAILER` asset by foreign key. It supports list with status and asset filters, a
  separate linked-from date range, `options` for Active assets showing chassis numbers,
  `current-by-prime-mover` and `current-by-tanker` lookups, create, update, close (sets the end date,
  appends `Close Remarks`), permanent delete, CSV/XLSX/PDF export, and import preview and commit that
  creates or updates on prime mover + tanker + linked-from. Exactly one Active link is allowed per
  prime mover and per tanker. Global asset writes remain admin-only, and every mutation is audited
  with before and after snapshots.
- Operation types are a hard-coded catalogue in `app/utils/operation_types.py` (ADR-019). The six
  types each map to one asset type. The eight categories each carry one stock sign:
  SET (opening and closing stock), IN (receipt), OUT (dispatch, export, draining, decanting) or
  NEUTRAL (ITT). `/api/operation-types` is read-only and reports live counts.
- Operation Master (`/api/operations`) stores location-scoped operations of those fixed types. The
  sign is derived from the category on every write. Code and name are unique per location and type,
  ignoring case, across every status. Active operations need an Active location. Deactivation keeps
  the row (no delete route), and import is create-only. Filters, a separate created-date range,
  server pagination, CSV/XLSX/PDF export and audit are included. Non-admin users see only the
  locations they are assigned to.
- Configurations dashboard (`/api/dashboard/modules/configurations`) reports operation types,
  categories, active operations and configured locations, with a per-type breakdown and quick links.

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
- Prime Mover-Tanker Link page under Master Data, and a new Configurations group between Master
  Data and Business (Module Dashboard, Operation Types, Operation Master). Both use the standard
  `resource:action` permissions (`prime_mover_tanker_links:*`, `operation_types:read`,
  `operations:*`). Link dialogs show a live warning when a chosen asset already has another Active
  link. Deletes and deactivations use an in-app confirmation pop-up instead of `window.confirm`.
- The confirmation pop-up is now a shared component, `components/common/ConfirmDialog.jsx`.
- Navy/white design system with light/dark/system theme support; no new side navigation or
  non-standard CRUD permissions.

### Deployment and schema

- Docker Compose remains PostgreSQL + FastAPI + nginx-served React; the cloud API deploy remains
  native Python on Render. SQLAlchemy `create_all` creates the Location, RoleLocation, Asset,
  AssetTank, AssetCalibrationTable, AssetCalibrationRow, PermissionPreset and
  PermissionPresetItem tables at startup, and the new `prime_mover_tanker_links` and `operations`
  tables with them; no Alembic baseline has been introduced yet. The permission catalog grows from
  30 to 39 standard rows with the `prime_mover_tanker_links`, `operation_types` and `operations`
  resources.

## 3. Verification state and remaining work

- Backend: `cd backend && python -m pytest -q` → **116 passed, 1 warning**. New coverage (36 tests):
  link validation, asset type and status checks, one-active-link rules, close, scope, import
  preview and commit, export, dashboard KPIs (`tests/test_prime_mover_tanker_links.py`); the fixed
  catalogue and sign derivation, uniqueness, location scope, deactivation, import, export, audit,
  RBAC and the Configurations dashboard (`tests/test_configurations.py`). Earlier coverage includes the master/assignment APIs, import preview and commit, hierarchy checks, Admin guards,
  standard permission enforcement, legacy grant migration, the hard-coded asset type catalog,
  unit conversion factors, chart validation, 2D/3D interpolation, and the permission preset cap,
  apply modes, apply guards and preset RBAC.
- Frontend: `cd frontend && npm run build` → **success** (Vite 8.3.4, 74 modules). The main chunk is 515 kB, above Vite's 500 kB warning threshold; the Configurations and link pages are not code-split yet.
- Dependency install: `cd frontend && npm ci` → **success, 0 reported vulnerabilities**.
- Live HTTP smoke tests through uvicorn and the Vite proxy → **36/36 checks** for the asset and
  calibration path and **78/78 checks** for the permission preset path (both end to end).
- A temporary jsdom harness rendered the real preset components and the updated assignment page
  against a stubbed API → **58/58 DOM checks** (harness not committed).
- Browser review (headless Chromium, live backend and Vite): Prime Mover-Tanker Link in light
  theme; Operation Master, Operation Types and the Configurations dashboard in dark theme. Each
  rendered without console errors. Dialogs (link, close, operation, deactivate and delete
  pop-ups), the Permission Presets confirm dialog after its extraction, and the light theme of the
  Configurations pages were **not** exercised in a browser in this delivery.
- PostgreSQL deployment-schema verification has **not** been run in this delivery (no browser binary is installable
  in the sandbox; the new tables were instead compiled through the PostgreSQL dialect). An XLSX
  wide-sheet calibration upload against a real Excel file has **not** been exercised (CSV wide
  layout has).
- Profile & Security enhancements, an Alembic migration baseline, report profile masters, Operation
  Entry (waiting for owner confirmation), OTMS Tracking Module Configuration, business operations, reports, backup, audit archive/retention and security-event
  dashboard remain planned.
