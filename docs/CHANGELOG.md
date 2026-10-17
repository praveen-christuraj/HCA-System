# HCA System — Changelog

Running log of every delivery (owner rule 12). Newest first. Each entry links to a detailed
note in [`changes/`](changes/). Verification evidence is recorded with the entry, not assumed.

---

## 2026-10-17 — User Management regrouping; Asset Master and Asset Calibration

**Note:** [`changes/2026-10-17-asset-master-and-calibration.md`](changes/2026-10-17-asset-master-and-calibration.md)

| Area | Delivered |
| --- | --- |
| Navigation | Location Master and Role Location Assignment moved under User Management, ordered User Master, Role Master, Location Master, Role Permission Assignment, Role Location Assignment, User Role Assignment. The `locations` permission moved to the User Management catalog category; bootstrap migrates existing rows. Master Data Management is now the asset module, gated by `assets:read`. |
| Asset Master | Hard-coded catalog of seven asset types (Storage Tank, Barge, Shuttle Vessel, FSO, Prime Mover, Tanker Trailer, Flowmeter) with no `asset_types` table. Assets are asset-type scoped with `Local`/`Global` scope — Local requires an active location, Global carries none. Tanks are declared with the asset in a typed child table. CRUD, filters, date range, CSV/XLSX import preview-and-commit, CSV/XLSX/PDF export, soft deactivation. |
| Asset Calibration | Charts are always three columns (tank name, dip/ullage, volume) — the OTMS template column designer is gone. Dip/ullage accepted in cm, mm or m; volume in litres, kilolitres or barrels; converted once into canonical **cm** and **bbl** with the supplied values retained. Long and wide (printed calibration book) layouts both accepted. One active chart per asset; replacement is audited with the row count and chart name it replaced. |
| Interpolation | Server-side engine. 2D is depth → volume within one tank; 3D resolves the tank name exactly first, then runs the 2D curve, so a barge's `2P` can never return `2S`'s volume. Every result carries `method`, bracketing points, `in_range` and warnings. Out-of-range readings are refused by default; clamping is opt-in, flagged, and capped at 5 cm outside the certified range. Single and batch lookup endpoints. |
| Validation | Tank name must match a tank declared on the asset; no repeated depth per tank; at least two points per tank; duplicate depths with differing volumes rejected; monotonicity reported per basis (dip rises with volume, ullage falls). Prime Mover and Flowmeter cannot require calibration; a calibrated asset must declare a tank; a tank with calibration rows cannot be removed. |
| RBAC / audit | New `assets` resource with standard `read`/`create`/`update`/`delete`. Asset location scoping reuses Role Location Assignment for non-admin users. Every create, update, deactivation, import, export, chart upload, chart delete and interpolation is audited. |
| Project memory | ADR-013 to ADR-017 record the regrouping, the hard-coded asset types, tank declaration, the fixed three-column chart shape with canonical units, and the interpolation provenance rule. |

**Verification**

- `cd backend && ./.venv/bin/python -m pytest -q` → `70 passed, 1 warning` (28 pre-existing + 42 new, including four XLSX upload tests
  and location-scope enforcement).
- `cd frontend && npm run build` → success (Vite 8.3.4, 66 modules).
- Live HTTP smoke test through uvicorn + the Vite proxy → 36/36 checks, including 750 mm → 7.5 bbl interpolation, 1P/2P tank-axis separation, mm+litre → cm+bbl conversion (1589.87294928 L → exactly 10 bbl), out-of-range refusal then flagged clamp, and wide-layout import.
- XLSX uploads covered by generated workbooks: a long sheet in m and kL converting to canonical cm and bbl, a multi-tank wide sheet, an undeclared-tank rejection, and an XLSX asset register import.
- Location scoping covered: a user whose role has location assignments sees only those locations plus Global assets, and is refused a single-asset read outside them.
- Not verified: manual light/dark review of the two new pages in a browser, and PostgreSQL schema creation for the four new tables (tests run on SQLite; `create_all` runs at startup and no Alembic baseline exists yet).

## 2026-10-17 — User, Role and Location Master modules

**Note:** [`changes/2026-10-17-user-role-location-masters.md`](changes/2026-10-17-user-role-location-masters.md)

| Area | Delivered |
| --- | --- |
| User Master | Added create/edit/deactivate, password reset, role management, permission-aware import/export and reserved-Admin safeguards. |
| Role Master | Added configurable role CRUD, standard permission assignment, filters, import and CSV/XLSX/PDF export. |
| Location Master | Added typed hierarchical locations with parent-cycle/assignment safeguards, CRUD, filters, import and CSV/XLSX/PDF export. |
| Assignment modules | Added Role Permission, Role Location and User Role pages/APIs with filtered pagination, audited replacement, CSV/XLSX preview-and-confirm import, and CSV/XLSX/PDF export. Imports validate all rows before changing assignments. |
| Permissions | Standard `resource:action` capabilities are provisioned idempotently from `RESOURCE_PERMISSION_DEFINITIONS`; legacy title-based grants migrate to standard permissions. Assignment writes use `assignments:write`. Reserved Admin protections are enforced. |
| Project memory | Updated Rule 11, architecture and module status to require automatic standard permission provisioning for every new page/resource. |

**Verification**

- `cd backend && ./.venv/bin/python -m pytest -q` → `26 passed, 1 warning`.
- `cd frontend && npm ci` → success, 0 reported vulnerabilities.
- `cd frontend && npm run build` → success (Vite 8.3.4).
- Manual browser/light-dark smoke tests and PostgreSQL deployment-schema verification remain outstanding.

## 2026-10-17 — Render API deployment switched to native Python 3 (no Dockerfile)

**Note:** [`changes/2026-10-17-render-python-runtime.md`](changes/2026-10-17-render-python-runtime.md)

| Area | Delivered |
| --- | --- |
| Deployment | `render.yaml` now defines a native Render Python web service instead of a Docker build: `env: python`, root `backend`, build `pip install -r requirements.txt`, start `python3 -m app.seed_admin && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`, `PYTHON_VERSION=3.12.8`, health check `/api/health`. The seed-first start command keeps the "no manual seed step" rule (ADR-006) intact on Render (ADR-010). `DEPLOY_CLOUD.md`, `README.md` and project memory updated. Docker Compose and the Dockerfiles remain unchanged for local/OTMS deployment. |

**Verification**

- `render.yaml` parses as valid YAML (PyYAML `safe_load`).
- `cd backend && python -m pytest -q` → `19 passed` (no application code changed).

## 2026-10-17 — Initial build: authentication, RBAC, audit, dashboards, User Master, Audit Trail, spreadsheets

**Note:** [`changes/2026-10-17-initial-build.md`](changes/2026-10-17-initial-build.md)

Rebuilt the OTMS foundation as HCA System with the changed structures required by the standing
rules. Nothing was copied verbatim where the owner rules change the design.

| Area | Delivered |
| --- | --- |
| Deployment | `docker-compose.yml` (PostgreSQL 16 + FastAPI + nginx-served React), `Makefile`, `.env.example`; identity bootstrap runs inside the backend container entrypoint, not as a manual step (rule 14). |
| Backend | FastAPI + SQLAlchemy 2, typed column-wise models only — no JSON/JSONB columns anywhere (rule 4). 37 routes. |
| Auth | JWT access + rotating refresh tokens with server-side revocation, TOTP 2FA, password policy, 5-attempt/15-minute lockout, forced first-password change. |
| RBAC | 26 catalogued permissions in 4 categories; reserved Admin role with full catalog; per-route permission dependencies; `GET /api/roles` and per-role permission assignment. |
| Audit | Mutating requests write audit rows with actor, module, action, entity, method, path, IP, user agent, status and `details_summary`; middleware writes a fallback row for unreported mutations; browser events persist through `POST /api/audit/ui-events`. |
| Dashboards | System summary (4 KPIs, 8 module cards, recent audited activity) and per-module dashboards; planned modules are labelled `Planned`, never faked. |
| User Master | Server-side paginated list, quick search, advanced filters, separate created-date range, read-only detail dialog, CSV/XLSX/PDF export, XLSX/CSV import with row-level preview before commit. |
| Audit Trail | Paginated log with module/category/outcome/actor filters, separate event-date range, truncated details, request path, CSV/XLSX/PDF export. |
| UI | Navy/white enterprise design system with light/dark/system themes, top-side dropdown navigation, no side navigation, no decorative animation or emojis. |
| Tests | 19 backend tests: auth lifecycle, refresh rotation, logout revocation, lockout, RBAC 403 + denial audit, audit persistence, pagination snapping, three-format exports, import preview/commit/XLSX. |

**Verification**

- `cd backend && .venv/bin/python -m pytest -q` → `19 passed`.
- `cd frontend && npm run build` → success, 51 modules.
- `python -m app.seed_admin` → 26 permissions, Admin role, `admin` account.
- Live API through the Vite proxy: health, login, `/auth/me` (26 permissions), `/system/status`.

**Known gaps (honest)**

- Master Data, Business, Reports and Back-up modules are registered as `Planned`; only their
  dashboards and permission placeholders exist.
- User Master is read-only apart from import; create/edit/reset-password screens are next.
- Module dashboards beyond User Management, Auditing and System are placeholders.
