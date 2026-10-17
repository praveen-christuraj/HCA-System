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
