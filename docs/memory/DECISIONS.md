# HCA System — Decision Log (ADR)

Architecture and product decisions of record. New decisions are added at the top with a date.
A decision changes only through a new entry that supersedes the old one.

---

## ADR-001 — Repositories are known as OTMS and Costing
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** `OTMS` always means <https://github.com/praveen-christuraj/hydrocarbon-accounting-otms>
and `Costing` always means <https://github.com/praveen-christuraj/WellCostingPro>. Architecture
and modules come from OTMS; critical basic modules and UI craft come from Costing.

**Consequences.** Reference material is read-only. Modules are re-implemented against this
project's memory, not pasted. Known OTMS issues are fixed during extraction.

---

## ADR-002 — No JSON columns anywhere
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS stores audit details and backup codes as `JSONB`. The owner requires
conventional column-wise storage.

**Decision.** No `JSON`/`JSONB`/document columns. Use typed columns; store collections in child
tables. Audit details become typed columns plus `details_summary` text. Backup codes become
`user_backup_codes` rows.

**Consequences.** More schema work per feature; better queryability, constraints and reporting.
API payloads remain nested JSON (transport only).

---

## ADR-003 — Audit coverage is three-layered
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** (1) Routers write detailed audit rows for domain actions. (2) Middleware writes a
fallback row for any mutation/denied request not already audited (context flag avoids
duplicates). (3) The SPA posts page visits and client actions to `/api/audit/ui-events`.

**Consequences.** "All actions on all pages" is actually persisted server-side, including
navigation and theme choices. Audit volume is higher; retention/archiving is a planned module.

---

## ADR-004 — Server-driven pagination with 20/50/100/200
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** List APIs accept `page` and `page_size` (20 default, allowed 20/50/100/200, hard
maximum 500 for exports) and return `items/total/page/page_size/pages/has_more`. Frontend lists
use server pagination; only small reference lists load in full.

**Consequences.** Predictable performance regardless of history size. Filters must be applied
server-side before pagination.

---

## ADR-005 — Docker topology mirrors OTMS, frontend served by nginx
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS runs the Vite dev server in its frontend container. That is not appropriate
for an enterprise deployment but the owner asked for the OTMS deployment method.

**Decision.** Keep the OTMS three-service topology and compose workflow (`docker compose up
--build`: PostgreSQL, backend, frontend). Improve the frontend image to a multi-stage build
served by nginx, which proxies `/api` to the backend. The browser uses same-origin relative
URLs.

**Consequences.** No CORS in production, no runtime Node process, smaller image. Local dev
still uses Vite with a proxy. This is an implementation improvement, not a topology change.

---

## ADR-006 — Administrator is seeded automatically by the container entrypoint
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS requires running `seed_admin.py` manually. The owner requires seeding while
building the Docker container itself.

**Decision.** `backend/docker-entrypoint.sh` waits for PostgreSQL, runs `python -m
app.seed_admin` (idempotent: Admin role, permission catalog, administrator account, audit
record), then starts uvicorn. Credentials come from `SEED_ADMIN_*` env vars; a random strong
password is generated and printed once when none is supplied.

**Consequences.** `docker compose up --build` is the only deployment command. Re-deploys never
duplicate the admin. Build-time seeding of a database is impossible without a running database,
so "during the build/stack bring-up" is implemented at first container start, which is the
earliest technically valid point and requires no operator action.

---

## ADR-007 — JWT access/refresh with database-checked permissions
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** Access tokens carry identity only (user id, username, jti). Roles and permissions
are read from the database on every request and returned to the client as a fresh snapshot at
login/`/auth/me`. Refresh tokens rotate; logout blacklists the token identifiers.

**Consequences.** Permission changes take effect immediately; no stale permission claims.
One extra join per authenticated request (indexed, acceptable).

---

## ADR-008 — Login page mirrors OTMS visual language with theme support
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** The split-screen login (navy identity panel + light form panel), brand copy,
password-strength meter, 2FA challenge and password-reset request mirror OTMS. The theme
selector is added to the login page itself so users can choose light/dark/system before
signing in. Errors appear inside the form card (near the action) and via the warning alert for
the unseeded-admin state.

**Consequences.** Visual continuity with OTMS while satisfying rules 2 and 10.

---

## ADR-009 — Boolean columns instead of "Yes"/"No" strings for new structures
**Date:** 2026-10-17 · **Status:** Accepted

**Decision.** New HCA System tables use real booleans (`force_password_change`, `totp_enabled`,
`force_2fa`, …). When OTMS modules are extracted, their Yes/No columns are converted to booleans
through a migration and their API contracts updated.

**Consequences.** Cleaner SQL and reporting; extraction requires mapping work per module.

---

## ADR-010 — Render deploys the API natively with python3 commands, not the Dockerfile
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** `render.yaml` first deployed the API from `backend/Dockerfile` (`runtime: docker`).
The owner asked to deploy on Render with the Python 3 runtime and plain `python3` commands
instead of a Docker image.

**Decision.** Render runs the API as a native Python web service (`env: python`,
`rootDir: backend`): build `pip install -r requirements.txt`, start
`python3 -m app.seed_admin && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`,
`PYTHON_VERSION=3.12.8`, health check `/api/health`. The seed-first start command preserves the
ADR-006 contract (no manual seeding) without the container entrypoint. `backend/Dockerfile`,
`backend/docker-entrypoint.sh` and `docker-compose.yml` stay unchanged and remain the local
deployment (ADR-005).

**Consequences.** Simpler, faster Render builds with no Docker layer; the same environment
contract (`DATABASE_URL`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `SEED_ADMIN_*`, `CORS_ORIGINS`).
Uvicorn must bind `0.0.0.0:$PORT` because Render injects the port. If the start command is ever
edited in the Render dashboard, the seed step must stay before uvicorn.

---

## ADR-011 — Standard resource/action permissions are provisioned from the page catalog
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** Costing uses standard `resource:action` capabilities; HCA's original User/Role
permissions were title-based and made exports and page additions inconsistent.

**Decision.** All page access uses the standard `read`, `create`, `update` and `delete` actions
for a registered resource. Assignment write operations share `assignments:write`. Every new
page resource is added to `RESOURCE_PERMISSION_DEFINITIONS` in
`backend/app/utils/default_permissions.py`; startup bootstrap idempotently provisions the
permissions, so no page ships without its standard catalog entries. Existing title-based grants
are migrated to the equivalent standard grants before their legacy rows are deactivated.

**Consequences.** Role grants are reusable across pages and API/UI enforcement; exports use
`read`, imports use `create`, and soft deactivation uses `update`. Dashboard, profile/security,
audit, security-event and system-health pages use standard resources. Their former named grants
are migrated to equivalent standard keys and deactivated at bootstrap; no named page permissions
remain in the active catalog.

---

## ADR-012 — Location assignments are typed hierarchical master data
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS includes Location Master and Role Location Assignment, but HCA's initial
schema had no location table and must not store assignment arrays as JSON.

**Decision.** Add a typed `locations` table with a self-referencing optional parent and a typed
`role_locations` association table with a unique role/location pair. User-to-role assignment
continues to use HCA's existing `user_roles` table. Locations are soft-deactivated; assignment
pages replace typed child rows under `assignments:write` and are audited.

**Consequences.** Location hierarchy and role scope can be filtered and joined in SQL; imports
use bounded CSV/XLSX preview/confirmation and preserve the same typed constraints.

---

## ADR-013 — Location Master and Role Location Assignment live under User Management
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** Location Master and Role Location Assignment shipped under Master Data Management.
The owner directed that both move under User Management, in the order User Master, Role Master,
Location Master, Role Permission Assignment, Role Location Assignment, User Role Assignment —
because location access is part of what a role grants, not operational reference data.

**Decision.** Move both pages into the User Management navigation group in that order, move the
`locations` permission resource into the `User Management` catalog category, add both pages to
the User Management module dashboard (KPI plus quick links), and repoint the Master Data module
dashboard at the asset module.

**Consequences.** `MODULE_PERMISSIONS["master-data"]` is now `assets:read`. Bootstrap migrates
the `locations` permission rows to the new category idempotently, so no manual data change is
needed. Master Data Management is left as the asset and calibration module.

---

## ADR-014 — Asset types are hard coded, not a soft-coded master
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS stores asset types in an editable `asset_types` table. That let an installation
rename or delete a type at runtime, and downstream code then had to guess an asset's nature from
free text — OTMS `asset_family.py` exists precisely because barge tickets were lost when a client
called their barge class `YADE`.

**Decision.** Ship a closed catalog of seven asset types — Storage Tank, Barge, Shuttle Vessel,
FSO, Prime Mover, Tanker Trailer, Flowmeter — in `backend/app/utils/asset_types.py`. There is no
`asset_types` table and no CRUD. The catalog is the single source of truth for the dropdown, for
validation, and for whether a type carries tanks or takes calibration. Import files may spell a
type any accepted way; aliases fold onto one code (`YADE` → `BARGE`).

**Consequences.** Rules that depend on an asset's nature are stable. Adding a type is a reviewed
code change rather than a runtime setting. Prime Mover and Flowmeter cannot be marked as
requiring calibration, and types that carry no tank reject tank declarations.

---

## ADR-015 — Tanks are declared with the asset and key the calibration chart
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** A barge, FSO or tanker trailer carries several compartments, and a calibration chart
is keyed by compartment name. OTMS had no tank master, so tank identity lived only inside
free-form calibration rows and could not be validated.

**Decision.** Add a typed `asset_tanks` child table, unique on `(asset_id, tank_name)`, populated
in the same dialog that creates the asset. Calibration rows reference `tank_id`, so a chart can
only describe compartments the asset actually has.

**Consequences.** A chart naming an undeclared compartment is rejected at preview. Removing a
tank that has calibration rows is blocked until the chart is deleted. The tank name becomes the
third interpolation axis, resolved exactly — never approximated to a neighbouring compartment.

---

## ADR-016 — Calibration charts have a fixed three-column shape, stored in canonical units
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS let each installation design its own calibration template columns
(`CalibrationTemplateColumn` with a user-chosen `interpolation_role`) and stored every row as
`row_data JSONB` keyed by those invented names. Nothing downstream could rely on a field
existing, and HCA forbids JSON columns outright.

**Decision.** A chart always has three columns — tank name, dip/ullage, volume. The template
master is therefore not a user-designed object: the shape is fixed in code and the user supplies
only the measurement basis and the units the file is written in. Accepted depth units are cm, mm
and m; accepted volume units are litres, kilolitres and barrels. Values are converted once on the
way in and stored as typed `Numeric` columns in canonical cm and bbl, alongside the values as
supplied. One chart is active per asset; uploading replaces it and the audit row records the row
count and chart name that were replaced.

**Consequences.** Interpolation is a pure function over typed columns, callable from the API and
from future business modules. Conversions are re-checkable because the source values are kept.
Conversion basis: 1 bbl = 158.987294928 L = 0.158987294928 m³, the same constant OTMS used, so
historical results reconcile.

---

## ADR-017 — Interpolation reports how a volume was derived instead of clamping silently
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** OTMS interpolated in the browser only, and its `linearInterpolation` clamped any
reading outside the chart to the first or last row and returned `0` for an empty table. A dip
above the certified range therefore produced a plausible volume with no signal that it was out of
range — a real custody risk.

**Decision.** Interpolate server-side. Every result carries a `method` (`exact`, `interpolated`,
`clamped_low`, `clamped_high`), the bracketing points, an `in_range` flag and any warnings.
Out-of-range readings are refused by default; holding the end volume is an explicit opt-in and is
still refused beyond 5 cm outside the certified range. A duplicated depth with two different
volumes is rejected rather than resolved arbitrarily.

**Consequences.** Business modules can consume the same engine the UI uses, and every resolved
volume can be defended from the audit trail. A chart that gains volume as the dip grows is
reported as a warning at upload, since that usually means a transposed column.

---

## ADR-018 — Permission presets are a capped, named template catalog, not a second role layer
**Date:** 2026-10-17 · **Status:** Accepted

**Context.** Maintaining many roles meant ticking the same standard permissions again for every
role. The owner asked for named presets that can be applied to a role instead, with a maximum of
20 presets and a name per preset. The obvious risk is that "presets" quietly become a second,
parallel authorization layer: roles inheriting from templates, templates inheriting from other
templates, and nobody able to say what a role can actually do.

**Decision.** A preset is a *template*, not a grant. `permission_presets` holds one typed row per
preset (name, description, status, `times_applied`, `last_applied_at`, creator) and
`permission_preset_items` holds one row per permission in the preset — never a JSON array
(rule 4). Applying a preset **copies** its permission ids into `role_permissions`; no foreign key
from a role to a preset survives the copy, so a role's effective access is still read from
`role_permissions` alone, exactly as before. The catalog is capped at `MAX_PERMISSION_PRESETS`
(default 20) counted across every preset row, and each preset must contain at least one active
permission. Application is an explicit `replace` or `add`, refused for the reserved Admin role and
for inactive roles or presets, bounded at `MAX_PRESET_APPLY_ROLES` roles per request, and subject
to the existing rule that a non-administrator may neither grant nor remove permissions they do not
hold themselves. Presets are administered with the new standard `permission_presets:read/create/
update/delete` capabilities; applying one additionally requires `assignments:write` because it
writes role grants.

**Consequences.** Roles stay flat and fully explainable — deactivating or editing a preset never
changes a role that already received it, and the audit row per role records the preset name, mode
and added/removed counts. Because a preset that has been applied is evidence of how live roles were
shaped, `DELETE` deactivates by default; a permanent delete (which frees a cap slot) is allowed only
while `times_applied` is zero. The cap keeps the list a curated set of templates rather than a
shadow permission table, and the remaining-slot count is returned with every list response so the
UI can say "18 of 20 free" instead of failing silently.
