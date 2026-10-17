# HCA System — Changelog

Running log of every delivery (owner rule 12). Newest first. Each entry links to a detailed
note in [`changes/`](changes/). Verification evidence is recorded with the entry, not assumed.

---

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
