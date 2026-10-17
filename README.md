# HCA System

Enterprise Hydrocarbon Accounting System — rebuilt from **OTMS** with changed structures and
additional logic, following the permanent project memory in [`docs/memory/`](docs/memory/).

- Architecture: FastAPI + SQLAlchemy + PostgreSQL, React + Vite, JWT auth, RBAC, audited by
  default, top-side navigation, navy/white enterprise UI.
- Current increment: **v0.1 — authenticated foundation, mirrored login page, module dashboards,
  User Master (list, filters, detail, CSV/XLSX import, CSV/XLSX/PDF export), Audit Trail and
  roles/permissions APIs, all audited and permission-gated.**
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

See [`DEPLOY_CLOUD.md`](DEPLOY_CLOUD.md) for the provider setup, environment variables, secure database configuration, deployment steps, and verification. `render.yaml` defines the Render API service and `vercel.json` configures SPA fallback. The existing Dockerfiles and Docker Compose deployment are intentionally retained unchanged.

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
