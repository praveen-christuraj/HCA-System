"""Database engine, session factory and declarative base.

PostgreSQL is used in Docker; SQLite is supported for local development and
the test suite. Schema changes for v0.1 are applied with ``create_all``;
Alembic is the planned migration tool for the next increment.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL


def _engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        # SQLite is single-file; allow the FastAPI thread pool to use it.
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,
    }


engine = create_engine(DATABASE_URL, **_engine_options(DATABASE_URL))

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a session and always closing it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create missing tables. Importing models registers the metadata."""
    from app import models  # noqa: F401  (side effect: register models)

    Base.metadata.create_all(bind=engine)
