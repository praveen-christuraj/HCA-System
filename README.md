# HCA System

Enterprise Hydrocarbon Accounting System — rebuilt from **OTMS** with changed structures and
additional logic, following the permanent project memory in [`docs/memory/`](docs/memory/).

- Architecture: FastAPI + SQLAlchemy + PostgreSQL, React + Vite, JWT auth, RBAC, audited by
  default, top-side navigation, navy/white enterprise UI.
- Current increment: **authenticated foundation; user/role/location/permission masters and
  presets; assets, calibration and prime mover links; fixed Operation Types/Operation Master;
  and one-page Operation Entry with OTMS payloads, live calculations, independent creation /
  review / submission / approval controls, typed records, reference masters, imports and exports.**
- Honest delivery status: [`docs/memory/MODULES.md`](docs/memory/MODULES.md).

## Quick start with Docker (OTMS deployment method)

```bash
cp .env.example .env          # set secrets and the admin password you want
docker compose up --build
```

- Frontend: <http://localhost:8080>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

The deployment is self-contained: the backend entrypoint waits for PostgreSQL, seeds the
permission catalog, the reserved **Admin** role and the administrator (idempotently), then
starts the API. If `SEED_ADMIN_PASSWORD` is empty, a strong password is generated and printed
once in the backend log:

```bash
docker compose logs backend | grep -A3 "ADMIN CREDENTIALS"
```

## Cloud deployment (Vercel + Render + Supabase)

See [`DEPLOY_CLOUD.md`](DEPLOY_CLOUD.md) for the provider setup, environment variables, secure database configuration, deployment steps, and verification. `render.yaml` deploys the API on Render's **native Python 3 runtime** — build `pip install -r requirements.txt`, start `python3 -m app.seed_admin && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` — so no Dockerfile is used on Render, and `vercel.json` configures SPA fallback. The existing Dockerfiles and Docker Compose deployment are intentionally retained unchanged.

## Local development (no Docker)

Requirements: Python 3.11+ and Node 20+.

```bash
# Backend
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./hca.db
export SEED_ADMIN_USERNAME=admin
export SEED_ADMIN_PASSWORD=Admin@12345
python -m app.seed_admin
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

Vite proxies `/api` to `http://127.0.0.1:8000`, so the browser always uses relative URLs and
the preview origin works without CORS changes.

Default local credentials when the environment above is used: `admin` / `Admin@12345`. Import
users from User Master with the CSV template in the import dialog; every file is validated
row-by-row before anything is written.

## Operation Entry

Open **Business → Operation Entry**. There is no Operation Template Master to customize:
Tank, Barge, Shuttle, FSO, Tanker Trailer and Flowmeter use their fixed OTMS payloads directly.
Prime Mover details come from the trailer's active link. Fixed Vessel Cycle and Stock Movement
alternatives are also available for Shuttle and FSO.

Configure active locations/assets/operations and actual calibration charts first. Under
**Configurations → Operation References**, supply Table 11 factors, meter configuration and
permanent seals where needed, and optionally set additional workflow policies. Table 11 factors
are never fabricated. Review and submission permissions are separate from ticket creation.

See [`docs/changes/2026-10-17-operation-entry.md`](docs/changes/2026-10-17-operation-entry.md)
for source parity, API/RBAC details, setup, verification and the boundary with still-planned
tracking/report modules.

## Tests and build

```bash
cd backend && python -m pytest -q
cd frontend && npm run build
```

## Project memory and rules

All contributors must follow [`docs/memory/PROJECT_MEMORY.md`](docs/memory/PROJECT_MEMORY.md)
and [`AGENTS.md`](AGENTS.md). Every change is logged in [`docs/CHANGELOG.md`](docs/CHANGELOG.md)
and documented under [`docs/changes/`](docs/changes/).

**Repository aliases:** `OTMS` = <https://github.com/praveen-christuraj/hydrocarbon-accounting-otms>;
`Costing` = <https://github.com/praveen-christuraj/WellCostingPro>.
