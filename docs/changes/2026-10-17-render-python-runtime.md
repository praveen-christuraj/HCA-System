# Render native Python deployment — 2026-10-17

## Purpose

Deploy the HCA System API on Render without a Dockerfile. The owner asked for Render's native
Python 3 runtime and plain `python3` commands instead of the Docker build that `render.yaml`
first used (and that `docker-compose.yml` still uses locally).

## Scope delivered

1. `render.yaml` switched from `runtime: docker` + `backend/Dockerfile` to a native Python web
   service: `env: python`, `rootDir: backend`, build `pip install -r requirements.txt`, start
   `python3 -m app.seed_admin && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`,
   `PYTHON_VERSION=3.12.8`, health check `/api/health`. The unsynced secret variables
   (`DATABASE_URL`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, `SEED_ADMIN_EMAIL`, `SEED_ADMIN_PASSWORD`,
   `CORS_ORIGINS`) are unchanged.
2. `DEPLOY_CLOUD.md` section 2 rewritten for the native runtime (Blueprint **or** manual Web
   Service with the exact build/start commands), including boot behaviour and the note that
   edits to the start command must keep the seed step.
3. `README.md` cloud section updated to describe the Python 3 deployment.
4. Memory updated: `docs/memory/ARCHITECTURE.md` §8 gained a cloud topology subsection;
   `docs/memory/DECISIONS.md` gained ADR-010.

## Design decisions applied

- **No Docker on Render.** Render's Python environment installs `backend/requirements.txt` and
  runs `python3` directly. `backend/Dockerfile`, `backend/docker-entrypoint.sh` and
  `docker-compose.yml` are untouched and remain the OTMS-style local deployment (ADR-005).
- **Seed is part of the start command (ADR-006 contract).** `python3 -m app.seed_admin` runs
  before uvicorn on every boot: it waits for PostgreSQL, creates the tables and seeds the
  permission catalog, the reserved Admin role and the administrator idempotently, printing the
  generated password once in the Render service logs when `SEED_ADMIN_PASSWORD` is empty.
  `BOOTSTRAP_ADMIN_ON_STARTUP=true` keeps the same bootstrap running in the FastAPI lifespan as
  a second safety net.
- **Bind to Render's port.** uvicorn listens on `0.0.0.0:$PORT`; Render routes traffic to the
  port it injects, so a fixed port would fail health checks.
- **Same environment contract.** Nothing about the variable set changes; secrets stay in the
  Render dashboard and out of Git.

## Scope not delivered (honest)

- Render-side provisioning (creating the service, setting secrets) is operator dashboard work;
  the repository only defines the Blueprint and the manual settings.
- No migration system yet; the schema is still created at boot.

## Verification

- `render.yaml` parses as valid YAML (PyYAML `safe_load`).
- `cd backend && python -m pytest -q` → `19 passed` (no application code changed).
