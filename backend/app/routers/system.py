"""Health, seed status and system administration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import APP_NAME, APP_VERSION, ENVIRONMENT
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Permission, Role, User
from app.services.bootstrap import admin_seeded
from app.utils.time import utcnow

router = APIRouter(tags=["System"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Public endpoint used by Docker health checks and the login page."""
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "admin_seeded": admin_seeded(db),
        "time": utcnow().isoformat() + "Z",
    }


@router.get("/system/status")
def system_status(
    user: User = Depends(require_permission("View System Health")),
    db: Session = Depends(get_db),
):
    db.execute(text("SELECT 1"))
    admin = (
        db.query(User)
        .filter(User.username == "admin")
        .first()
    )
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "environment": ENVIRONMENT,
        "database_dialect": db.bind.dialect.name if db.bind is not None else "unknown",
        "admin_seeded": admin_seeded(db),
        "seed_username": admin.username if admin else None,
        "counts": {
            "users": db.query(User).count(),
            "roles": db.query(Role).count(),
            "permissions": db.query(Permission).count(),
        },
    }
