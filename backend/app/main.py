"""HCA System API entry point.

Lifespan:
  1. create missing tables,
  2. seed the permission catalog and reserved Admin role,
  3. seed the administrator if ``BOOTSTRAP_ADMIN_ON_STARTUP`` is enabled.

The Docker entrypoint runs the same idempotent bootstrap before uvicorn, so a
plain ``docker compose up --build`` is sufficient (owner rule 14).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS, APP_NAME, APP_VERSION, BOOTSTRAP_ADMIN_ON_STARTUP
from app.database import SessionLocal, init_db
from app.middleware import AuditMiddleware, SecurityHeadersMiddleware
from app.routers import audit_logs, auth, dashboard, permissions, roles, system, users
from app.services.bootstrap import bootstrap_identity

logger = logging.getLogger("hca")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _run_bootstrap() -> None:
    db = SessionLocal()
    try:
        report = bootstrap_identity(db)
        admin = report["admin"]
        logger.info(
            "Bootstrap complete: permissions created=%s updated=%s, admin=%s (%s)",
            report["permissions_created"],
            report["permissions_updated"],
            admin["username"],
            admin["message"],
        )
        # The generated password is printed by ``python -m app.seed_admin`` in
        # the container entrypoint, never by the web process.
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if BOOTSTRAP_ADMIN_ON_STARTUP:
        _run_bootstrap()
    yield


app = FastAPI(
    title=f"{APP_NAME} API",
    version=APP_VERSION,
    description=(
        "Hydrocarbon Accounting System. Every mutating request is audited; every "
        "endpoint is RBAC-gated; list endpoints are server-paginated."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditMiddleware)

API_PREFIX = "/api"

app.include_router(system.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(roles.router, prefix=API_PREFIX)
app.include_router(permissions.router, prefix=API_PREFIX)
app.include_router(audit_logs.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {
        "message": f"{APP_NAME} API is running",
        "version": APP_VERSION,
        "health": "/api/health",
        "docs": "/docs",
    }
