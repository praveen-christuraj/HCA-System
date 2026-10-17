# Cloud deployment: Vercel + Render + Supabase

The Dockerfiles and `docker-compose.yml` remain the supported Docker deployment and are unchanged. This guide deploys the React SPA to Vercel, the FastAPI API to Render, and PostgreSQL to Supabase. On Render the API runs on the **native Python 3 runtime** with plain `python3` commands — the backend Dockerfile is not used in the cloud. No credentials belong in Git.

## 1. Create Supabase PostgreSQL database

1. Create a Supabase project and save its database password.
2. In **Project Settings → Database → Connection string**, choose the **Session pooler** URI (recommended for Render) and copy it. Use port `5432`; do not use the Supabase REST/API URL. Replace the password placeholder and append `?sslmode=require` (or `&sslmode=require` if the URI already has query parameters).
3. Keep the URI private. SQLAlchemy accepts `postgres://` and normalizes it; `postgresql://` is also supported.

The backend creates its current v0.1 tables automatically on first start. Back up data before redeploying schema changes; this project does not yet have a migration system.

## 2. Deploy API on Render (native Python 3 — no Docker)

`render.yaml` deploys the API as a native Python web service. Render installs `backend/requirements.txt` during the build, then the start command runs plain `python3`: the idempotent administrator bootstrap first, uvicorn on `0.0.0.0:$PORT` second. The backend Dockerfile plays no part on Render; it stays in the repository for `docker compose` deployments.

1. In Render, choose **New → Blueprint**, connect this repository and select `render.yaml`. Alternatively create a Web Service manually with these settings:
   - Runtime: **Python** (native environment — do not select Docker)
   - Root Directory: `backend`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python3 -m app.seed_admin && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/api/health`
   - Environment Variable: `PYTHON_VERSION=3.12.8` (any Render-supported Python 3.10+ works; the codebase targets 3.12 like `backend/Dockerfile`).
2. Set the unsynced environment variables in the Render service dashboard:
   - `DATABASE_URL`: the Supabase Session pooler URI above.
   - `JWT_SECRET_KEY`: a unique random secret (e.g. `openssl rand -base64 48`).
   - `ENCRYPTION_KEY`: another independent random secret.
   - `SEED_ADMIN_EMAIL`: your administrator email.
   - `SEED_ADMIN_PASSWORD`: a strong unique password satisfying the application's password policy. The bootstrap runs automatically on startup; keep this value safe. Leave it empty to have a strong password generated and printed once in the Render service logs.
   - `CORS_ORIGINS`: the exact Vercel production origin, e.g. `https://hca-system.vercel.app` (comma-separate any additional trusted origins; no trailing slash).
3. Deploy. On every boot the start command first runs `python3 -m app.seed_admin` (waits for PostgreSQL, creates the tables, seeds the permission catalog, the reserved Admin role and the administrator idempotently — no manual seed step, the same contract as the Docker entrypoint), then `python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` serves the API. Wait for `/api/health` to report healthy. Copy the service URL, e.g. `https://hca-system-api.onrender.com`.

Render's free web services may sleep when idle and take time to wake. Use a paid always-on service for production. Do not expose database credentials or secrets to Vercel.

## 3. Deploy SPA on Vercel

1. Import the repository into Vercel. Set **Root Directory** to `frontend`; Vercel detects Vite. Build command `npm run build`, output directory `dist`.
2. Add the Vercel project URL to Render's `CORS_ORIGINS` and redeploy/restart the API if you did not configure it earlier.
3. Add the Vercel environment variable `VITE_API_BASE_URL` with the API URL plus `/api`, for example `https://hca-system-api.onrender.com/api`.
4. Deploy (or redeploy after setting the variable). `vercel.json` supplies SPA history fallback routing. The API client uses this absolute base URL in cloud deployments and continues to use relative `/api` locally/Docker.
5. Open the Vercel URL, sign in with the seeded admin username/password, and verify health at `https://<render-service>.onrender.com/api/health`.

## 4. Updating and operations

Push changes to the connected GitHub branch to trigger deployments (or deploy manually from each provider). Keep `VITE_API_BASE_URL` set in Vercel Production, Preview, and Development environments as appropriate; preview deployments should use an API CORS allowlist that includes their preview origin, or test against the production frontend. Never use `CORS_ORIGINS=*` with credentials in production. Rotate secrets only with care: changing JWT secret invalidates existing tokens, and changing the encryption key can make previously encrypted data unreadable. If the Render start command is ever edited in the dashboard, keep the seed step (`python3 -m app.seed_admin`) before uvicorn.

## Local and Docker deployment remain available

For the existing Docker setup, follow the Quick start in `README.md` and continue using `docker compose up --build`. Do not replace the Dockerfiles with provider-specific build artifacts. The Dockerfiles are not used by Render.
