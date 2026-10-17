# HCA System — Module Map and Status

> Honest status board. **Never describe a Planned module as shipped.**
> Updated whenever a module is added, partially delivered or completed.
> Last updated: 2026-10-17

---

## 1. Module map

| Module | Purpose | Status |
| --- | --- | --- |
| **Home / Portfolio** | Cross-module KPIs, module status, recent audited activity | **Delivered (v0.1)** |
| **User Management** | User Master, Role Master, standard role permissions, Role Permission, User Role, profile and security | **Core identity and access delivered and verified:** user/role CRUD, imports/exports, permission assignments, user-role assignments, reserved-Admin protections. Profile/security baseline remains available; further security administration is planned. |
| **Master Data Management** | Location Master, hierarchical locations, Role Location Assignment; later asset types, assets, tanks/vessels, report profiles and operation types | **Location Master and Role Location Assignment delivered and verified:** typed hierarchy, CRUD, import/export and audited assignments. Additional reference masters remain planned. |
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
- Location Master uses typed location and parent columns, validates parent cycles, supports
  create/update/soft-deactivation, bounded CSV/XLSX import preview/commit and filtered exports.
- Role Permission, Role Location and User Role assignment APIs support filtered/paginated lists,
  CSV/XLSX/PDF exports, audited replacement and bounded CSV/XLSX preview/commit imports. Each
  assignment import validates the complete file before replacing any row; the reserved Admin
  role/account cannot be modified through these assignment modules.
- Shared master import parser caps files at 5,000 data rows. Role permissions accept
  `role_name,permission_names`; role locations accept `role_name,location_codes`; user roles
  accept `username,role_names`. Multi-value cells use semicolon-separated standard keys/names.
- Master Data dashboard KPIs and quick links are live and permission-filtered.

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
- Navy/white design system with light/dark/system theme support; no new side navigation or
  non-standard CRUD permissions.

### Deployment and schema

- Docker Compose remains PostgreSQL + FastAPI + nginx-served React; the cloud API deploy remains
  native Python on Render. SQLAlchemy `create_all` creates new Location/RoleLocation tables at
  startup; no Alembic baseline has been introduced yet.

## 3. Verification state and remaining work

- Backend: `cd backend && ./.venv/bin/python -m pytest -q` → **26 passed, 1 warning**. Coverage
  includes the master/assignment APIs, import preview and commit, hierarchy checks, Admin guards,
  standard permission enforcement and legacy grant migration.
- Frontend: `cd frontend && npm run build` → **success** (Vite 8.3.4 production build).
- Dependency install: `cd frontend && npm ci` → **success, 0 reported vulnerabilities**.
- Manual browser smoke tests, PostgreSQL deployment-schema verification and light/dark visual
  review of the new pages have **not** been run in this delivery.
- Profile & Security enhancements, an Alembic migration baseline, asset-type/asset masters,
  business operations, reports, backup, audit archive/retention and security-event dashboard
  remain planned.
