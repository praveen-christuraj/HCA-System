# HCA System — Module Map and Status

> Honest status board. **Never describe a Planned module as shipped.**
> Updated whenever a module is added, partially delivered or completed.
> Last updated: 2026-10-17 (Operation Entry delivery)

---

## 1. Module map

| Module | Purpose | Status |
| --- | --- | --- |
| **Home / Portfolio** | Cross-module KPIs, module status, recent audited activity | **Delivered (v0.1)** |
| **User Management** | User Master, Role Master, Location Master, Permission Presets, Role Permission, Role Location, User Role assignment, profile and security | **Core identity, location access and RBAC delivered and verified:** user/role/location CRUD, imports/exports, permission assignments, capped named permission presets applied to roles in replace/add mode, role-location assignments, user-role assignments, reserved-Admin protections. Profile/security baseline remains available; further security administration is planned. |
| **Master Data Management** | Asset Master over seven hard-coded asset types, tanks declared per asset, Asset Calibration with fixed three-column charts and dip-to-volume interpolation, Prime Mover-Tanker Link | **Asset Master, Asset Calibration and Prime Mover-Tanker Link delivered and verified:** fixed asset type catalog, Local/Global scoping, typed tanks, chart upload in cm/mm/m and L/kL/bbl converted to canonical cm/bbl, 2D and 3D interpolation, exports and full audit. The link pairs one prime mover with one tanker trailer, allows one Active link per asset, and supports close, import and export. Report profiles remain planned. Flowmeter configuration is now delivered under Operation References. |
| **Configurations** | Fixed Operation Types mapped to asset types, the fixed operation categories with their stock signs, and the location-scoped Operation Master that feeds Operation Entry | **Operation Types and Operation Master delivered and verified:** hard-coded catalogue (ADR-019), read-only type and category pages, location-scoped operations with derived sign, unique code and name per location and type, deactivation, import, export and dashboard. Operation References now supplies Table 11, meter configurations, permanent seals, workflow policies and voyage guards. Editable OTMS Tracking Module Configuration remains out of scope; HCA keeps its fixed operation types. |
| **Business / Operations** | Operation entry, transactions, workflow, tank/vessel operations, export operations, tracking | **Operation Entry delivered:** six fixed module payloads, two fixed legacy layouts, live calculations, Draft editing, reviewed submission/approval, recall/reject/cancel, linked receiving, audit and version protection. Detailed tracking/comparison reports, task inboxes, correction and export-operation workflows remain planned. |
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

- Operation Entry's fixed payload catalogue replaces Operation Template customization. All module
  inputs/calculations are stored in typed tables, with child stage/dip/seal/meter rows and immutable
  saved calibration/operation snapshots. Client-calculated values are recomputed on save.
- Entry creation/edit, review, submit/approve, recall/reject/cancel and receiving permissions are
  independent. Workflow policies, any-of-four party reads, own-origin writes, narrowly scoped
  receiving references, version checks and unique active sender links are enforced by the API.
- Table 11 uses uploaded factors only. Meter factors and master seals come from typed references;
  source CCF/rounding/mass fallbacks and shuttle/FSO arithmetic are verified with OTMS fixtures.
- Entry and reference CSV/XLSX imports validate before commit; exports include filtered registers
  and complete ticket snapshots in CSV/XLSX/PDF. History and lookups are paginated.
- Approval writes one immutable posting per ticket. Generated voyages support audited close/reopen,
  closed-voyage entry guards and the FSO closed-shuttle-discharge lookup. Full tracking and stock
  reconciliation pages are not implied by these foundations.

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

- Business → Operation Entry retains the source asset-specific field groups, calculation-card
  order, barge before/after/net columns, tanker quick actions and receiver-copy safeguards. It has
  searchable server-backed selectors, a fixed-layout summary, read-only saved review, separate date
  filters, imports/exports, a paginated register and history. No operation template designer exists.
- Configurations → Operation References has gated Table 11, meters, seals, policy and voyage tabs.
  Both new pages are lazy-loaded; their CSS is scoped and works in both themes.
- Shared master import previews now expose all rows through 20/50/100/200 pagination.

### Deployment and schema

- Docker Compose remains PostgreSQL + FastAPI + nginx-served React; cloud deploy remains native
  Python on Render. Startup creates the 22 new typed operational/reference tables and idempotently
  seeds the extended **60-permission** catalogue. There are **42 tables** in total, with no JSON
  columns. Existing baseline table columns are unchanged; no manual seed step or Alembic baseline
  is introduced. No OTMS legacy-data migration is claimed.

## 3. Verification state and remaining work

- Backend: `cd backend && python -m pytest -q` → **182 passed, 1 warning**, including 66 Operation
  Entry tests. Nine golden numerical fixtures were executed from OTMS source commit
  `5eed361486fa56ad636da62e238d73059b0e2a2c`. All six payloads, both scalar layouts, imports,
  exact compartments, Ullage, CCF, Table 11, typed round-trips, reference integrity, scoped RBAC,
  policies, review, workflow states, stale writes, local/global receivers and exports are covered.
- Frontend: `npm run build` → success; new pages are separate lazy chunks. The existing main
  bundle remains about 516 kB, above Vite's 500 kB advisory.
- Browser: **18 Playwright tests** against live FastAPI and Vite. All six primary forms are entered,
  saved, reopened, reviewed and submitted in light and dark. The suite also covers source KPI/row
  order, fixed legacy layouts, URL prefills, linked tanker receiving, configuration tabs,
  Cancel-only dialogs, login and the empty entry shell at 1024/768 widths. Screenshots were
  inspected for the tank/barge/tanker/meter layouts; screenshots and browser binaries are ignored.
- Schema: every table compiled through the PostgreSQL dialect; no JSON type. A live PostgreSQL
  database and Docker deployment were **not** run. Production calibration/reference acceptance and
  OTMS data migration remain installation work, not covered by synthetic verification fixtures.
- Earlier deliveries' evidence remains in their dated notes (master/assignment and preset APIs,
  calibration unit conversion, link/configuration browser review and import/export smoke tests).
- Planned: Profile & Security enhancements, an Alembic migration baseline, report profiles,
  configurable tracking-module mappings, full tracking/comparison/report screens, task-inbox
  routing, correction workflows, export operations, backup and audit archive/security dashboards.
  Do not describe those as delivered by the entry approval/posting foundation.
