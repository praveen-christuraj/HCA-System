# Cloud deployment: Vercel + Render + Supabase

The Dockerfiles and `docker-compose.yml` remain the supported Docker deployment and are unchanged. This guide deploys the React SPA to Vercel, the FastAPI API to Render, and PostgreSQL to Supabase. No credentials belong in Git.

## 1. Create Supabase PostgreSQL database

1. Create a Supabase project and save its database password.
2. In **Project Settings → Database → Connection string**, choose the **Session pooler** URI (recommended for Render) and copy it. Use port `5432`; do not use the Supabase REST/API URL. Replace the password placeholder and append `?sslmode=require` (or `&sslmode=require` if the URI already has query parameters).
3. Keep the URI private. SQLAlchemy accepts `postgres://` and normalizes it; `postgresql://` is also supported.

The backend creates its current v0.1 tables automatically on first start. Back up data before redeploying schema changes; this project does not yet have a migration system.

## 2. Deploy API on Render

1. In Render, choose **New → Blueprint**, connect this repository and select `render.yaml`. Alternatively create a Web Service with root directory `backend`, Docker runtime, and `backend/Dockerfile`.
2. Set the Blueprint's unsynced environment variables in the Render service dashboard:
   - `DATABASE_URL`: the Supabase Session pooler URI above.
   - `JWT_SECRET_KEY`: a unique random secret (e.g. `openssl rand -base64 48`).
   - `ENCRYPTION_KEY`: another independent random secret.
   - `SEED_ADMIN_EMAIL`: your administrator email.
   - `SEED_ADMIN_PASSWORD`: a strong unique password satisfying the application's password policy. The bootstrap runs automatically on startup; keep this value safe.
   - `CORS_ORIGINS`: the exact Vercel production origin, e.g. `https://hca-system.vercel.app` (comma-separate any additional trusted origins; no trailing slash).
3. Deploy. Wait for `/api/health` to report healthy. Copy the service URL, e.g. `https://hca-system-api.onrender.com`.

Render's free web services may sleep when idle and take time to wake. Use a paid always-on service for production. Do not expose database credentials or secrets to Vercel.

## 3. Deploy SPA on Vercel

1. Import the repository into Vercel. Set **Root Directory** to `frontend`; Vercel detects Vite. Build command `npm run build`, output directory `dist`.
2. Add the Vercel project URL to Render's `CORS_ORIGINS` and redeploy/restart the API if you did not configure it earlier.
3. Add the Vercel environment variable `VITE_API_BASE_URL` with the API URL plus `/api`, for example `https://hca-system-api.onrender.com/api`.
4. Deploy (or redeploy after setting the variable). `vercel.json` supplies SPA history fallback routing. The API client uses this absolute base URL in cloud deployments and continues to use relative `/api` locally/Docker.
5. Open the Vercel URL, sign in with the seeded admin username/password, and verify health at `https://<render-service>.onrender.com/api/health`.

## 4. Updating and operations

Push changes to the connected GitHub branch to trigger deployments (or deploy manually from each provider). Keep `VITE_API_BASE_URL` set in Vercel Production, Preview, and Development environments as appropriate; preview deployments should use an API CORS allowlist that includes their preview origin, or test against the production frontend. Never use `CORS_ORIGINS=*` with credentials in production. Rotate secrets only with care: changing JWT secret invalidates existing tokens, and changing the encryption key can make previously encrypted data unreadable.

## Local and Docker deployment remain available

For the existing Docker setup, follow the Quick start in `README.md` and continue using `docker compose up --build`. Do not replace the Dockerfiles with provider-specific build artifacts.
