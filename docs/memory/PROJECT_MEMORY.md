# HCA System — Project Memory

> **Status: permanent project memory. Mandatory reading before any code change.**
> Last updated: 2026-10-17
> Owner-maintained standards. If code and this document disagree, the document wins until the
> owner approves a change. Every change to the application must also update
> [`docs/CHANGELOG.md`](../CHANGELOG.md) and, when it creates a new pattern, this memory.

---

## 1. What this project is

**HCA System** is the rebuilt Hydrocarbon Accounting System. It is an enterprise,
business-oriented platform for hydrocarbon operations, inventory, measurement and reporting.
The codebase is a rebuild of **OTMS** with changed structures and additional logic; it is not a
line-for-line copy.

The application must always look and behave like a system used for eight hours a day in an
operations office: dense, quiet, predictable, auditable and permission-driven.

---

## 2. Reference repositories (owner aliases)

These aliases are part of the project vocabulary. Whenever the owner says the alias, it means
the repository below. Do not substitute another repository.

| Alias | Repository | How it is used |
| --- | --- | --- |
| **OTMS** | <https://github.com/praveen-christuraj/hydrocarbon-accounting-otms> | Primary source of application architecture and the modules to extract into HCA System, with the structural changes and additional logic required here. |
| **Costing** | <https://github.com/praveen-christuraj/WellCostingPro> | Source of critical basic modules and the UI design guidance in `docs/UI_skills` and `.agent/memory/design-system.md`. |

**Source-of-truth order**

1. This memory (owner instructions).
2. OTMS for application architecture, module boundaries, API shape and deployment topology.
3. Costing `docs/UI_skills` and its design-system memory for visual craft and interaction quality.
4. The existing HCA System code.

When OTMS and this memory disagree, **this memory wins**. Typical deliberate differences from
OTMS are recorded as decisions in [`DECISIONS.md`](DECISIONS.md).

---

## 3. Standing product conventions (mandatory on every page and module)

These 15 rules are non-negotiable. They apply to existing pages, new pages, background jobs,
imports, exports, admin screens and everything added later. Code review must reject violations.

### Rule 1 — Audit every action on every page

- Every user action is recorded: sign-in, sign-out, failed sign-in, navigation/open page,
  create, update, delete, restore, assign, approve, import, export, print, filter changes,
  theme changes, permission changes, backup/restore operations, and security events.
- Backend: every mutating API request writes an `audit_logs` row with actor, module, action,
  entity, method, path, IP address, user agent, status code and timestamp. API middleware
  writes a fallback record for any mutation that did not produce a specific record.
- Frontend: client-only actions (page visits, filters, theme, client-side print/export) are
  sent to the backend audit endpoint (`POST /api/audit/ui-events`) so they are persisted, not
  merely kept in browser memory.
- Audit records are append-only. Normal users can never modify or delete them. Only an
  administrator with the dedicated permission may purge/archive, and that purge is itself
  audited.
- Every new page ships with auditing switched on by default. "Auditing later" is not accepted.

### Rule 2 — Light and dark themes, user-selectable

- The user chooses **Light**, **Dark** or **System**, and the choice is persisted per browser.
- Both themes are designed together: background, surface, text, muted text, borders, table
  headers, chart colours, focus rings, status colours and disabled states all have explicit
  dark values. Never ship a page that works only in light mode.
- Every screen, including the login page, must be usable and readable in both themes.
- Colour decisions come from design tokens, never from hardcoded page-level colours.
- The theme choice is audited (`Appearance / Change Theme`).

### Rule 3 — Top-side navigation with dropdown menus

- Primary navigation is a horizontal, top-side bar with module dropdown menus. There is **no
  side navigation** for primary navigation.
- The active module is visibly marked; dropdowns support keyboard navigation, Escape and
  outside-click dismissal, and close on route change.
- Navigation items are filtered by the user's RBAC permissions, so a user never sees a menu
  entry they cannot open.
- Page breadcrumbs are carried by the page heading (module / page), not by a second bar.

### Rule 4 — No JSON storage in the database

- Never store JSON, JSONB, serialized objects, documents or key-value payload blobs in a
  database column. Use conventional, typed, **column-wise** tables: one column per business
  attribute, with proper foreign keys, indexes and constraints.
- API requests and responses may be nested JSON — that is transport. Persistence must not be.
- Collections (for example a user's backup codes, audit details, line items, assignment lists)
  are stored as child tables with one row per value, not as a JSON array.
- Audit "details" are stored as typed columns plus a human-readable summary text, never as a
  JSON document. Add a dedicated column when a new auditable attribute is needed.
- Database Browser/report features may render JSON responses; they may not create JSON
  columns.

### Rule 5 — Pagination on every list

- Every page that lists data is paginated. Supported page sizes are **20, 50, 100, 200**
  (plus larger sizes only when a documented operational need exists). Default is **20**.
- Pagination is server-driven for API lists. The response always carries `items`, `total`,
  `page`, `page_size`, `pages` and `has_more`.
- Client-side grids may paginate in the browser, but must expose the same page-size options and
  show the total count.
- Never render an unbounded list. Never fetch "everything and page in the browser" for a
  server-backed dataset.

### Rule 6 — Easy and advanced filters; dates kept separate

- Every list page has a **quick search** (easy filter) across the main text columns.
- Every list page has an **advanced filter** panel that can filter on any meaningful criterion
  exposed by the data: text contains/equals/starts-with, status, category, role, module,
  numeric ranges, and so on.
- **Date and date-range filters are a separate control group** with their own From/To pickers,
  visually and structurally distinct from the general filters. Do not bury dates inside the
  advanced filter list.
- Active filters are visible, individually removable and resettable in one action.
- Filter changes that produce a server request are audited as `Apply Filter` actions.

### Rule 7 — Import and export

- List/data pages provide **import from Excel** in both **`.xlsx` and `.csv`** formats, with a
  preview, row-level validation and clear error reporting before committing.
- List/data pages provide **export to `.xlsx`, `.csv` and PDF**.
- Exports respect the current filters and (where practical) the current selection, and the
  export itself is audited with format, row count and filter summary.
- Endpoints that legitimately cannot accept import (immutable audit records, generated reports)
  must still support export and must state why import is unavailable.
- Never write formula-injection-capable cells (`=`, `+`, `-`, `@`) into CSV/XLSX without
  sanitising them.
- PDFs are print-grade: company/system header, generated-at timestamp, filter summary, page
  numbers and no clipped columns.

### Rule 8 — Module-wise dashboards

- Every module has its own dashboard/summary page showing module KPIs, status breakdowns,
  recent activity and quick links into the module's pages.
- The module map is: **User Management, Master Data Management, Business modules, Report
  modules, Back-up modules, Auditing modules**, and any module added later (for example
  Configuration, Operations, Export Operations).
- Each module also appears on the portfolio Home dashboard with a live count/status.
- Do not present an unbuilt module as shipped. Planned modules are labelled **Planned** and
  explain what will be delivered.

### Rule 9 — Navy Blue and White enterprise theme

- The palette is professional **Navy Blue and White** in light mode and a navy-based dark
  palette in dark mode. Navy is the single brand/action colour; status colours are reserved
  for status.
- No green branding, no gradients used as decoration, no glassmorphism, no emojis, no playful
  illustrations, no unnecessary animation. Motion is limited to short state feedback and is
  disabled under `prefers-reduced-motion`.
- Typography, spacing, radii, control heights and table density follow
  [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md).
- Layouts are enterprise-grade: clear module boundaries, consistent page headers, dense data
  tables, disciplined forms and print-friendly reports.

### Rule 10 — Alerts near the data, preferably pop-ups

- Validation errors appear next to the field that caused them.
- Action failures appear next to the action that caused them (inline alert) or as a modal/pop-up.
- Confirmation of destructive actions is always a pop-up dialog.
- Never use a detached global banner at the top of the application for a field or action error.
- Toast/snackbar may confirm a completed action, but must not be the only place an error is
  explained. Errors use `role="alert"`; success messages use `role="status"`.
- Data-entry dialogs close only via **Cancel** (or a successful save) — not via backdrop click,
  Escape or a close icon.

### Rule 11 — RBAC and auditing on every page by default

- Every page is created with RBAC from the start. Access is controlled by the administrator
  through roles and permissions. There is no "open" page.
- The frontend hides or disables actions the user cannot perform; the **API is the
  authorization authority** and re-checks every request. Never rely on hidden buttons alone.
- **Only standard `resource:action` permissions may be used for application pages.** Use the
  standard actions `read`, `create`, `update` and `delete`; cross-page role/user/location
  assignment writes use the shared `assignments:write` capability. Do not create page-specific
  names such as `View User`, `Export Role` or `Edit Location`.
- Every new page/module must be registered in
  `backend/app/utils/default_permissions.py` under `RESOURCE_PERMISSION_DEFINITIONS` before
  its route/UI is added. Bootstrap automatically creates and refreshes those permissions
  idempotently; no manual permission seed is allowed. The same catalog drives API enforcement,
  permission assignment UI and frontend route/action gating.
- Read/list/detail/export use `<resource>:read`; create/import use `<resource>:create`; edits
  and soft-deactivation use `<resource>:update` (or `<resource>:delete` only for a true
  delete capability). Assignment pages read with the relevant standard resource permissions
  and write with `assignments:write`.
- Register dashboards, profile/security, audit, security-event and system-health views as
  standard resource capabilities too. During bootstrap, migrate known legacy title-based grants
  to the corresponding standard keys before deactivating the old rows; no named page permissions
  remain in the active catalog.
- Every page, action and export is auditable by default (Rule 1).
- The reserved **Admin** role holds the full catalog and cannot be locked out by configuration.
- The administrator can grant/revoke any standard permission per role; permission changes are audited.

### Rule 12 — Document every change in Markdown under `docs/`

- Every change to the application must be documented in `.md` form and committed under
  [`docs/`](..). This is the permanent memory.
- Each delivery gets an entry in [`docs/CHANGELOG.md`](../CHANGELOG.md) with date, summary,
  affected areas and verification evidence.
- Each non-trivial delivery also gets a dedicated note under [`docs/changes/`](../changes/)
  describing purpose, design, database changes, API changes, RBAC/audit impact, UI changes,
  migration/rollback notes and test evidence.
- Update [`PROJECT_MEMORY.md`](PROJECT_MEMORY.md), [`ARCHITECTURE.md`](ARCHITECTURE.md),
  [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md) or [`MODULES.md`](MODULES.md) when a change introduces
  or alters a project-wide pattern. Undocumented work is incomplete work.

### Rule 13 — Use OTMS and Costing as the extraction sources

- Extract application modules from **OTMS**, adapting them to this memory and to the changed
  structures in HCA System.
- Use **Costing** for critical basic modules and for UI craft.
- Follow **OTMS for application architecture** (FastAPI + SQLAlchemy backend, React/Vite
  frontend, PostgreSQL, JWT auth, RBAC catalog, module routers, top navigation, audit trail,
  Docker compose topology) and **Costing `docs/UI_skills`** for visual quality.
- Do not copy known OTMS issues. When a module is extracted, it must be reviewed against all
  15 standing rules and adjusted, not pasted.

### Rule 14 — Seed the administrator during the Docker build/deploy

- The administrator is created automatically as part of bringing the Docker stack up (image
  build + first container start). There is no manual "run this script later" step.
- The seed is idempotent: re-deploying never duplicates or overwrites the administrator.
- Credentials and profile come from environment variables (`SEED_ADMIN_USERNAME`,
  `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`, …). If no password is supplied, a strong random
  one is generated and printed once to the container log.
- The Admin role and the full permission catalog are seeded with the administrator in the same
  transaction-safe run.
- The seeded account must be audited (`System / Administrator Seeded`).
- The login page shows a "no administrator yet" warning if the API reports `admin_seeded=false`.

### Rule 15 — UI from Costing `docs/UI_skills`; architecture from OTMS

- Before building UI, read [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md), which applies the UI_skills
  guidance (frontend-design, UI/UX Pro Max, taste-skill, impeccable, interface-design,
  Vercel web-design-guidelines) to this product.
- UI must be accessible (keyboard, focus, contrast, labels, reduced motion), dense and
  consistent.
- Application architecture follows OTMS. Do not invent a different stack, folder model,
  authentication scheme or deployment topology without a recorded decision.

---

## 4. Delivery checklist (paste into every task)

- [ ] RBAC permission added to the catalog and enforced in the API; UI gated.
- [ ] Audit records written for create/update/delete/import/export/print/security events.
- [ ] Light and dark themes both verified.
- [ ] Top-side navigation entry added (permission-filtered), no side nav.
- [ ] No JSON column introduced anywhere.
- [ ] Server pagination with 20/50/100/200 and total counts.
- [ ] Quick search + advanced filters + separate date range.
- [ ] XLSX/CSV import (where applicable), XLSX/CSV/PDF export.
- [ ] Module dashboard updated with real KPIs.
- [ ] Navy/white enterprise styling; no emojis, no decorative animation.
- [ ] Alerts inline or pop-up; dialogs close only via Cancel.
- [ ] Change documented in `docs/CHANGELOG.md` and `docs/changes/<date>-<topic>.md`.
- [ ] Backend tests pass; frontend build passes; login smoke-tested in both themes.

---

## 5. Non-negotiables for this rebuild

1. The login page is mirrored from OTMS visual language (split identity panel + light form
   panel) and enhanced with the theme selector, real backend authentication, 2FA readiness,
   password-reset request and the administrator-seed warning.
2. The Docker deployment follows the OTMS three-service topology (PostgreSQL, FastAPI backend,
   React frontend) with automatic migrations and administrator seeding on stack startup.
3. Old OTMS structures that conflict with this memory are changed deliberately (no JSON, typed
   audit columns, child tables for collections, server pagination, top navigation, persistent
   UI action auditing).
4. Nothing unbuilt is described as done. The module map in [`MODULES.md`](MODULES.md) is the
   honest status board.
