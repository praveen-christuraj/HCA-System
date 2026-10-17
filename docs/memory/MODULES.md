# HCA System — Module Map and Status

> Honest status board. **Never describe a Planned module as shipped.**
> Updated whenever a module is added, partially delivered or completed.
> Last updated: 2026-10-17

---

## 1. Module map

The target module structure (from the owner instructions and OTMS) is:

| Module | Purpose | Status |
| --- | --- | --- |
| **Home / Portfolio** | Cross-module KPIs, module status, recent audited activity | **Delivered (v0.1)** |
| **User Management** | Users, roles, permissions, role-permission assignment, user-role assignment, profile & security | **Foundation delivered**: login, RBAC catalog, admin seeding, user/role/permission APIs, module dashboard, user list, XLSX/CSV import with preview, CSV/XLSX/PDF export. Create/edit dialogs and assignment screens: **In progress** |
| **Master Data Management** | Locations, asset types, assets, calibration templates, tanks/vessels, company report profiles, operation types | **Planned** (OTMS extraction) |
| **Business / Operations** | Operation entry, transactions, workflow, tank/vessel operations, export operations, tracking | **Planned** (OTMS extraction) |
| **Report Modules** | Tank stock ledger, out-turn, material balance, tanker transaction, tracking reports | **Planned** (OTMS extraction) |
| **Back-up Modules** | Backup settings, backup jobs, restore requests and validation | **Planned** (OTMS extraction) |
| **Auditing Modules** | Audit trail, security events, UI activity, module audit dashboard | **Delivered (v0.1)**: audit trail with filters, pagination and CSV/XLSX/PDF export; module dashboard. Security-event view and archive/purge: **Planned** |
| **System / Administration** | Health, seed status, application settings, notifications | **Foundation delivered**: health, seed status. Settings/notifications: **Planned** |

## 2. What v0.1 actually contains

- Backend: FastAPI application, JWT auth (login, refresh, logout, me), TOTP login challenge,
  password-reset request, account lockout, RBAC catalog + enforcement, typed audit trail with
  middleware fallback and persisted UI events, users/roles/permissions APIs, user import
  (XLSX/CSV preview + commit), audit list and three-format export, dashboard summary endpoints,
  health/seed status.
- Frontend: mirrored OTMS login page with theme selection, 2FA and reset flows; authenticated
  shell with top navigation and dropdowns; portfolio dashboard; module dashboards; user list
  (server pagination, quick + advanced filters, separate date range, CSV/XLSX/PDF export,
  import dialog); audit trail (server pagination, filters, CSV/XLSX/PDF export); inline 403
  panel from the permission guard; user menu with theme switcher.
- Deployment: Docker Compose (PostgreSQL + FastAPI + nginx React), schema creation via
  `create_all` for v0.1 (Alembic is the next step), automatic idempotent seeding of
  permissions, the Admin role and the administrator inside the backend container startup.

## 3. Next increments

1. User Management CRUD screens and assignment screens; profile & security (password change,
   2FA enrolment, backup codes).
2. Alembic migration baseline; replace `create_all`.
3. Master Data Management extraction from OTMS (locations, asset types, assets) with full
   import/export, filters and module dashboards.
4. Audit archive/retention, security-event dashboard.
5. Business modules, operations and report modules from OTMS, each with dashboard, RBAC,
   auditing, pagination, filters and imports/exports.
6. Backup module and restore validation.
7. Generalise the delivered user import (preview, row errors, XLSX/CSV) into a shared
   master-data import framework.
8. Automated browser checks for the login and shell in both themes.
