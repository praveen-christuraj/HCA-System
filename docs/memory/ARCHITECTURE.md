# HCA System — Architecture

> Derived from **OTMS** (see [PROJECT_MEMORY](PROJECT_MEMORY.md#2-reference-repositories-owner-aliases)),
> adapted to the standing product conventions. This is the architecture of record.

---

## 1. Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Frontend | React 19, Vite, React Router, plain CSS design tokens | No side navigation; top bar + module dropdowns. ExcelJS/jsPDF are used for client-side exports where a server export is not needed. |
| Backend | FastAPI (Python 3.12), SQLAlchemy 2, Pydantic 2 | Layered: routers → services → models. Dependency-injected sessions. |
| Database | PostgreSQL 16 in Docker; SQLite for local tests/dev | No JSON/JSONB columns (`PROJECT_MEMORY` rule 4). |
| Auth | JWT access + refresh tokens, bcrypt password hashing, optional TOTP 2FA | Permission set is read from the database on every request, never trusted from the token. |
| Audit | `audit_logs` table + API middleware + client action endpoint | Append-only; typed columns only. |
| Packaging | Docker Compose: `postgres`, `backend`, `frontend` | Same topology and env style as OTMS. Frontend is served by nginx and proxies `/api` to the backend. |

---

## 2. Repository layout

```
HCA-System/
├── backend/
│   ├── app/
│   │   ├── config.py             # env configuration, CORS, seed settings
│   │   ├── database.py           # engine/session/Base/get_db
│   │   ├── models.py             # SQLAlchemy models (typed columns only)
│   │   ├── schemas.py            # Pydantic request/response models
│   │   ├── main.py               # app factory, lifespan seeding, middleware, routers
│   │   ├── dependencies/         # auth + RBAC dependencies
│   │   ├── routers/              # one router per module (auth, users, roles, assets, audit...)
│   │   ├── services/             # audit, RBAC catalog, dashboards, imports, calibration engine
│   │   ├── utils/                # jwt, security, pagination, permissions, asset types, units
│   │   └── seed_admin.py         # idempotent admin + catalog seeding (standalone)
│   ├── tests/                    # pytest suite (SQLite)
│   ├── Dockerfile
│   └── docker-entrypoint.sh      # wait for DB → seed → serve
├── frontend/
│   ├── src/
│   │   ├── api/                  # apiClient + per-module API helpers
│   │   ├── components/
│   │   │   ├── common/           # Icon, DataTable-ready primitives, dialogs
│   │   │   └── layout/           # AppShell, TopNavigation, UserMenu
│   │   ├── context/              # ThemeProvider, AuthContext
│   │   ├── data/                 # navigation map (permission-gated)
│   │   ├── hooks/                # usePermissions, useApi
│   │   ├── pages/                # LoginPage, Home, module dashboards, lists
│   │   ├── styles/               # tokens.css, base.css, components.css, login.css
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile
│   └── nginx.conf
├── docs/
│   ├── memory/                   # permanent project memory (this folder)
│   ├── changes/                  # one note per delivery
│   ├── CHANGELOG.md              # running change log (rule 12)
│   └── UI_skills                 # Costing UI guidance reference
├── docker-compose.yml
├── .env.example
└── Makefile
```

---

## 3. Request flow

```
Browser (React SPA)
  │  fetch /api/<router>/<endpoint>  (relative URL; nginx/Vite proxies to backend)
  ▼
FastAPI middleware
  ├─ CORS
  ├─ AuditMiddleware: identifies actor from JWT, writes fallback audit rows for
  │  mutations/denials that routers did not audit explicitly, sets request id
  ▼
Router (auth, users, roles, permissions, audit, dashboard)
  ├─ require_permission("users:read") etc. → 403 if missing
  ├─ validate payload (Pydantic)
  ├─ service / query layer
  │    ├─ paginated list helper (page, page_size ∈ 20/50/100/200)
  │    └─ create_audit_log(...) before commit
  ▼
PostgreSQL
```

### Response envelope for lists

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0,
  "has_more": false
}
```

Filters are query parameters (`search`, `status`, `department`, `role_id`, `date_from`,
`date_to`, …). Date filters are supplied separately from general filters.

---

## 4. Authentication and RBAC

### Login

1. `POST /api/auth/login` validates username/password using bcrypt.
2. Failed attempts increment `failed_login_count`; five failures lock the account for 15
   minutes. Every failure is audited.
3. If TOTP is enabled, a `auth_login_challenges` row is created and the response is
   `{requires_2fa: true, challenge_id, user_hint}`. `POST /api/auth/2fa/verify` completes it.
4. On success the API returns access/refresh JWTs plus the user's effective roles and
   permissions. Tokens are stored client-side; refresh is attempted once on a 401.
5. `POST /api/auth/logout` blacklists the presented token identifiers.
6. `GET /api/auth/me` rehydrates the session on page load.

### Authorization

- Every router declares a standard capability such as `Depends(require_permission("users:read"))`.
- `get_user_permissions` unions active permissions across the user's active roles on each
  request. Deactivating a role or permission takes effect immediately.
- The reserved `Admin` role is identified by role name and bypasses individual permission
  checks. The admin account cannot be locked out by configuration.
- The frontend `usePermissions()` hook mirrors the backend rules for hiding/disabling UI.
  Hiding UI is a convenience, **not** security.

### Permission catalog

`backend/app/utils/default_permissions.py` is the single source of truth. It groups
permissions by module and is used by:

- startup seeding (`seed_default_permissions`),
- the standalone seed script,
- `GET /api/permissions/catalog` for the RBAC matrix UI.

Page permissions use only standard `resource:action` keys (`read`, `create`, `update`,
`delete`). `assignments:write` is the shared write capability for cross-page assignment
modules. An action that belongs to two capabilities at once uses `require_all_permissions` —
applying a permission preset needs `permission_presets:read` **and** `assignments:write`. Every page resource must be added to `RESOURCE_PERMISSION_DEFINITIONS` before its
API/UI is implemented; startup bootstrap provisions the catalog idempotently. List/detail/export
use `read`, create/import use `create`, and edits/soft-deactivation use `update`. Dashboard,
profile, audit, security and system pages are registered as standard resources too. Bootstrap
migrates existing title-based grants to their standard keys before deactivating the old rows;
no named page permissions remain in the active catalog.

---

## 5. Audit design (typed, no JSON)

`audit_logs` columns:

| Column | Purpose |
| --- | --- |
| `module_name` | User-visible module, e.g. `User Master`, `Authentication` |
| `action` | Verb, e.g. `Create`, `Update`, `Login Success`, `Export`, `Open Page` |
| `category` | `Authentication`, `Data Change`, `Security`, `Export`, `Navigation`, `Administration` |
| `entity_type`, `entity_id`, `entity_label` | What was affected |
| `actor_user_id`, `actor_username`, `actor_full_name` | Who did it (null for anonymous failed logins, username retained) |
| `http_method`, `request_path`, `status_code` | Transport context |
| `ip_address`, `user_agent` | Origin |
| `outcome` | `Success` or `Failure` |
| `old_status`, `new_status` | State transition where relevant |
| `remarks`, `details_summary` | Human-readable explanation (no serialized objects) |
| `created_at` | UTC timestamp |

Three writers:

1. **Routers** — explicit, detailed records for domain actions.
2. **AuditMiddleware** — fallback record for any mutation or denied request not already audited
   (a context flag prevents duplicates).
3. **`POST /api/audit/ui-events`** — client-side actions (page visits, filters, theme, print).

Audit rows are never updated or deleted by application code. The audit list endpoint is
read-only and itself permission-gated.

---

## 6. Database conventions

- One table per entity; one column per business attribute.
- Surrogate integer primary keys; explicit unique constraints and indexes.
- `created_at` / `updated_at` on mutable records; UTC timestamps.
- Booleans are real `BOOLEAN` columns (not `"Yes"/"No"` strings).
- Enumerations are short `VARCHAR` columns with documented values (e.g. `Active`, `Inactive`,
  `Locked`). A lookup table is used when the values are user-managed.
- Collections are child tables (`user_backup_codes`, `role_permissions`, `user_roles`,
  `permission_preset_items`, …).
- Soft delete is represented by an explicit nullable `deleted_at` (and `deleted_by`) column on
  master data, never by a JSON flag.
- No `JSON`, `JSONB`, `HSTORE`, serialized pickle or document columns.

### Asset and calibration domain

`Asset` carries the hard-coded `asset_type_code` (no `asset_types` table — see ADR-014),
`asset_scope` (`Local`/`Global`) and a nullable `location_id` that is mandatory for `Local`
assets. `AssetTank` is a child table unique on `(asset_id, tank_name)`.

`PermissionPreset` is a named, reusable template of standard permissions, capped at
`MAX_PERMISSION_PRESETS` (default 20) with one `PermissionPresetItem` row per permission. Applying
a preset copies its permission ids into `role_permissions`; no role keeps a foreign key to a
preset, so effective access is always resolved from `role_permissions` alone (ADR-018).

`AssetCalibrationTable` is one active chart per asset; `AssetCalibrationRow` stores each point as
typed `Numeric` columns — `dip_cm` and `volume_bbl` in canonical units, plus
`source_dip_value`/`source_volume_value` exactly as the chart supplied them. `dip_cm` holds dip
*or* ullage in centimetres per the parent chart's `measurement_basis`, so every payload that
exposes it also exposes the basis.

Canonical units are **cm** and **bbl**. Accepted source units are cm/mm/m and L/kL/bbl, converted
in `app/utils/units.py` using 1 bbl = 158.987294928 L = 0.158987294928 m³ — the same constant OTMS
used, so historical results reconcile. Interpolation lives server-side in
`app/services/calibration_engine.py` and every result reports its `method`, bracketing points and
`in_range` flag rather than clamping silently (ADR-017).

---

## 7. Frontend architecture

- `App.jsx` restores the session, shows the login screen when unauthenticated, and mounts the
  router + `AppShell` when authenticated.
- `AppShell` renders: skip link, navy brand bar, permission-filtered top navigation with
  dropdowns, theme/user menu, main content, audit footer.
- `ThemeProvider` sets `data-theme` on `<html>`, persists `light|dark|system`, updates
  `color-scheme` and the browser theme colour. No page hardcodes colours.
- `apiClient` uses relative `/api` URLs, attaches the bearer token, retries once after refresh,
  and surfaces backend `detail` messages as errors.
- `usePermissions` is the only place that decides admin status and permission membership.
- `actionLogger` buffers nothing important: page visits and UI actions are POSTed to the
  backend audit endpoint (fire-and-forget) so they survive the browser session.

---

## 8. Deployment

### Docker topology (OTMS method)

```
docker compose up --build
  ├── postgres  (postgres:16, named volume, healthcheck)
  ├── backend   (FastAPI image, entrypoint waits for DB → seeds → uvicorn :8000)
  └── frontend  (Node build stage → nginx :80, proxies /api to backend)
```

- Backend entrypoint: `docker-entrypoint.sh` waits for PostgreSQL, runs
  `python -m app.seed_admin` (idempotent — Admin role, permission catalog, administrator), then
  starts uvicorn. This satisfies the "seed while building the stack" rule: `docker compose up
  --build` is the only command needed.
- Frontend nginx serves the SPA and proxies `/api/` to `http://backend:8000/`, so the browser
  uses same-origin relative URLs (no CORS, no build-time backend URL).
- Environment is supplied through `.env` (see `.env.example`); secrets are never baked into
  images.
- Local development without Docker: SQLite (`DATABASE_URL=sqlite:///./hca.db`), Vite dev server
  proxying `/api` to `http://127.0.0.1:8000`.

### Cloud topology (Render + Vercel + Supabase)

- The API deploys on Render as a **native Python web service** (`render.yaml`, ADR-010): Render
  installs `backend/requirements.txt`, then the start command runs `python3 -m app.seed_admin`
  (waits for PostgreSQL, seeds idempotently) and `python3 -m uvicorn app.main:app --host 0.0.0.0
  --port $PORT`. The Dockerfile is not used on Render.
- PostgreSQL is external (e.g. the Supabase Session pooler); the SPA is built and served by
  Vercel (`vercel.json` SPA fallback) and calls the API via `VITE_API_BASE_URL`. Operator steps
  live in `DEPLOY_CLOUD.md`.

### Health

`GET /api/health` returns:

```json
{"status": "ok", "admin_seeded": true, "version": "0.1.0"}
```

The login page uses `admin_seeded` to show the first-run administrator warning.

---

## 9. Testing and verification

- Backend: `cd backend && python -m pytest -q` (SQLite; covers login, lockout, RBAC, audit,
  pagination and admin seeding).
- Frontend: `cd frontend && npm run build` (production bundle must succeed).
- Manual: login in light and dark, failed login, session restore, permission-filtered menu,
  audit trail pagination/filters/export, inline permission-denied panel, user import preview
  and commit, user and audit exports in three formats.
- Every delivery records its evidence in `docs/changes/<date>-<topic>.md`.

---

## 10. Deliberate differences from OTMS

Recorded in [DECISIONS.md](DECISIONS.md). Summary:

| Area | OTMS | HCA System |
| --- | --- | --- |
| Audit details | `JSONB` details + JSON backup codes | Typed columns, child table for backup codes |
| Audit coverage | Router-level audit | Router + middleware fallback + persisted UI actions |
| Pagination | Mixed server/client, 50 default | Server-driven, 20 default, 20/50/100/200 |
| Frontend deploy | Vite dev server in container | Multi-stage build served by nginx with `/api` proxy |
| Theme | Light/dark/system token layer | Same, extended to the login page and persisted |
| Admin seed | Manual `seed_admin.py` | Automatic idempotent seed in the container entrypoint |
| Navigation | Top nav with large menu | Same pattern, module-first groups, permission-filtered |
| Yes/No strings | Many `"Yes"/"No"` columns | Real booleans for new structures |
| Asset types | Editable `asset_types` master table | Hard-coded catalog of seven types in code |
| Tanks | No tank master; identity inside calibration rows | Typed `asset_tanks`, declared with the asset |
| Calibration schema | User-designed template columns + `row_data` JSONB rows | Fixed three columns; typed `Numeric` rows in canonical cm/bbl |
| Calibration units | Assumed cm and bbl | cm/mm/m and L/kL/bbl accepted, converted once, source kept |
| Interpolation | Browser-only, silent clamping, `0` for an empty table | Server-side; method, bracketing points and out-of-range refusal |


## 11. Fixed Operation Entry layer (ADR-020)

- `routers/operation_entries.py` → `services/operation_entry_access.py` and
  `services/operation_entry_service.py` → typed header/module/child tables. The fixed catalogue
  is `utils/operation_entry_payloads.py`; there is no template CRUD or JSON persistence.
- `services/quantity_engine.py` ports OTMS formulas and uses the shared fail-closed calibration
  engine. `services/table11.py` queries uploaded typed reference rows. The browser's source
  layouts calculate immediately, `/calculate` validates live, and save recomputes authoritatively.
- Source-compatible payload serialization belongs to the operation service rather than the
  generic master serializers. Snapshot reference fields protect historical tickets when masters
  change. Approval writes exactly one immutable `operation_postings` row with the status/audit
  transition in the same transaction.
- Read scope is the union of origin/sender/receiver/destination party scope; mutation scope is
  origin-only. A validated receiving link is the narrow exception for the foreign sender asset's
  calibration context, not unrestricted master access.
- Creation/editing, reviews, submissions, approvals, receiving tickets, reference management,
  policies and voyage controls have independent standard resource capabilities. Permissions are
  still resolved from live roles on every request. Optimistic ticket versions reject stale writes.
- `routers/operation_entry_import.py` groups fixed scalar CSV/XLSX rows into validated Draft
  tickets atomically. `routers/operation_references.py` owns the typed supporting masters,
  policy memberships and voyage close/reopen controls.
- `pages/OperationEntry.jsx` and `pages/OperationReferences.jsx` are lazy-loaded. The original
  measurement layouts live in `components/operationLayouts/`; narrow adapters translate scoped
  HCA reference projections without changing business input keys. No browser call targets a
  backend localhost address.
- New operational lists, lookup selectors and status history use standard pagination. Only a
  single selected asset's bounded chart is loaded as one calculation document (50,000 points
  max); tickets are bounded to 200 tanks/meters. This is not an unbounded master list.
- `frontend/tests/operation-entry.spec.js` runs against a real API/Vite proxy. See
  `playwright.config.js` and the delivery note for isolated test setup. Numerical OTMS fixtures
  are in `backend/tests/fixtures/otms_quantity_golden.json`.

## 12. Operation Tracking layer (ADR-022)

- `routers/operation_tracking.py` (prefix `/api/operation-tracking`) serves:
  - the Transaction Register (`/transactions`);
  - Barge (`/barge/*`), Tanker (`/tanker*`) and Shuttle / FSO (`/{shuttle|fso}/voyages*`) tracking;
  - the FSO reports (`/fso/reports/{otr|material-balance|outturn}`);
  - a CSV/XLSX/PDF export for each.

  Pure derivation helpers live in `services/operation_tracking.py`: barge event resolution and
  comparison, tanker seal/quantity checks, shuttle movement totals and the FSO report figures.
- State is derived on every read from Approved `operation_entries` within
  `scoped_entries(party=True)`. The persisted facts are `barge_timeline_events`,
  `tanker_receipt_acknowledgements` and `operation_voyages`. Mutations lock the affected rows,
  write a typed audit entry and commit once.
- Ticket workflow transitions remain in `routers/operation_entries.py`. The register UI calls
  those endpoints, so there is still one state machine.
- Frontend:
  - pages live under `pages/` (lazy);
  - shared pieces live in `components/operationTracking/` (`TicketWorkflow`, `TrackingKit`,
    `VoyageTracking`);
  - styles are in `styles/operation-tracking.css`;
  - the module dashboard key is `operation-tracking`, and its home card uses `any_permissions`.
