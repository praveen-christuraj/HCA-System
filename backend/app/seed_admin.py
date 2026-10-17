"""Idempotent administrator bootstrap (owner rule 14).

Run automatically by ``docker-entrypoint.sh`` before uvicorn starts:

    python -m app.seed_admin

The script waits for the database, creates missing tables, then seeds the
permission catalog, the reserved Admin role and the administrator account.
It never overwrites an existing administrator.

Credentials:
  * ``SEED_ADMIN_USERNAME``  (default ``admin``)
  * ``SEED_ADMIN_EMAIL``
  * ``SEED_ADMIN_PASSWORD``  (if empty, a strong password is generated and
    printed once here)
"""

from __future__ import annotations

import sys
import time

from sqlalchemy import text

from app.database import SessionLocal, engine, init_db
from app.services.bootstrap import bootstrap_identity


def wait_for_database(attempts: int = 60, delay_seconds: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print(f"[seed] Database reachable (attempt {attempt})")
            return
        except Exception as exc:  # noqa: BLE001 - startup diagnostics
            last_error = exc
            print(f"[seed] Waiting for database ({attempt}/{attempts})...")
            time.sleep(delay_seconds)
    raise RuntimeError(f"Database not reachable after {attempts} attempts: {last_error}")


def main() -> int:
    print("=" * 68)
    print(" HCA System — administrator bootstrap")
    print("=" * 68)

    wait_for_database()
    init_db()

    db = SessionLocal()
    try:
        report = bootstrap_identity(db)
    except Exception as exc:  # noqa: BLE001 - fail the container loudly
        db.rollback()
        print(f"[seed] ERROR: {exc}")
        return 1
    finally:
        db.close()

    admin = report["admin"]
    print(
        f"[seed] Permissions: created={report['permissions_created']} "
        f"updated={report['permissions_updated']}"
    )
    print(f"[seed] Admin role id={report['admin_role_id']}")

    if admin["created"]:
        print(f"[seed] Administrator created: {admin['username']}")
        if admin["generated_password"]:
            print("-" * 68)
            print(" ADMIN CREDENTIALS (shown once — store them securely)")
            print(f"   Username: {admin['username']}")
            print(f"   Password: {admin['generated_password']}")
            print(" Change this password after the first sign-in.")
            print("-" * 68)
        else:
            print("[seed] Password supplied through SEED_ADMIN_PASSWORD.")
    else:
        print(f"[seed] {admin['message']}")

    print("[seed] Bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
