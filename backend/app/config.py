"""Application configuration.

All runtime configuration is environment driven (12-factor). No secret or
environment-specific value is baked into the image. See ``.env.example``.
"""

from __future__ import annotations

import os
import secrets


APP_NAME = "HCA System"
APP_VERSION = "0.1.0"

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Docker supplies PostgreSQL; local development and tests use SQLite.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./hca.db" if not IS_PRODUCTION else "",
).strip()
# Supabase and Render often provide postgres:// URLs; SQLAlchemy expects the
# explicit PostgreSQL dialect name. Keep psycopg2 as the driver (requirements).
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set in production")

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if not JWT_SECRET_KEY:
    if IS_PRODUCTION:
        raise ValueError("JWT_SECRET_KEY must be set in production")
    JWT_SECRET_KEY = secrets.token_urlsafe(64)

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()
if not ENCRYPTION_KEY:
    if IS_PRODUCTION:
        raise ValueError("ENCRYPTION_KEY must be set in production")
    ENCRYPTION_KEY = secrets.token_urlsafe(48)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

MAX_FAILED_LOGINS = int(os.getenv("MAX_FAILED_LOGINS", "5"))
ACCOUNT_LOCK_MINUTES = int(os.getenv("ACCOUNT_LOCK_MINUTES", "15"))
LOGIN_CHALLENGE_MINUTES = int(os.getenv("LOGIN_CHALLENGE_MINUTES", "5"))

# ---------------------------------------------------------------------------
# CORS (only needed when the SPA is served from a different origin)
# ---------------------------------------------------------------------------
_cors_origins = os.getenv("CORS_ORIGINS", "*").strip()
if _cors_origins == "*":
    ALLOWED_ORIGINS = ["*"]
else:
    ALLOWED_ORIGINS = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]

# ---------------------------------------------------------------------------
# First-run administrator seeding (owner rule 14)
# ---------------------------------------------------------------------------
# The Docker entrypoint runs ``python -m app.seed_admin`` before starting the
# API, so a plain ``docker compose up --build`` creates the administrator.
BOOTSTRAP_ADMIN_ON_STARTUP = _as_bool(os.getenv("BOOTSTRAP_ADMIN_ON_STARTUP"), True)
SEED_ADMIN_USERNAME = os.getenv("SEED_ADMIN_USERNAME", "admin").strip() or "admin"
SEED_ADMIN_EMAIL = os.getenv("SEED_ADMIN_EMAIL", "admin@hca-system.local").strip()
SEED_ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "").strip()
SEED_ADMIN_FULL_NAME = os.getenv("SEED_ADMIN_FULL_NAME", "System Administrator").strip()
SEED_ADMIN_DEPARTMENT = os.getenv("SEED_ADMIN_DEPARTMENT", "IT Administration").strip()
SEED_ADMIN_DESIGNATION = os.getenv("SEED_ADMIN_DESIGNATION", "System Administrator").strip()

# ---------------------------------------------------------------------------
# Pagination (owner rule 5)
# ---------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = 20
PAGE_SIZE_OPTIONS = (20, 50, 100, 200)
MAX_PAGE_SIZE = 500
MAX_EXPORT_ROWS = 50_000
