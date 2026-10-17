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
from app.routers import (
    asset_calibration,
    assets,
    audit_logs,
    auth,
    dashboard,
    locations,
    operation_entries,
    operation_entry_import,
    operation_references,
    operation_types,
    operations,
    permission_presets,
    permissions,
    prime_mover_tanker_links,
    role_locations,
    roles,
    system,
    user_roles,
    users,
)
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
app.include_router(locations.router, prefix=API_PREFIX)
app.include_router(role_locations.router, prefix=API_PREFIX)
app.include_router(assets.router, prefix=API_PREFIX)
app.include_router(asset_calibration.router, prefix=API_PREFIX)
app.include_router(prime_mover_tanker_links.router, prefix=API_PREFIX)
app.include_router(operation_types.router, prefix=API_PREFIX)
app.include_router(operations.router, prefix=API_PREFIX)
app.include_router(operation_entries.router, prefix=API_PREFIX)
app.include_router(operation_entry_import.router, prefix=API_PREFIX)
app.include_router(operation_references.router, prefix=API_PREFIX)
app.include_router(user_roles.router, prefix=API_PREFIX)
app.include_router(permissions.router, prefix=API_PREFIX)
app.include_router(permission_presets.router, prefix=API_PREFIX)
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
