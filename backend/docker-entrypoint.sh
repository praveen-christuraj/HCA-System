#!/bin/sh
set -eu

echo "[entrypoint] HCA System backend starting"
echo "[entrypoint] Seeding permission catalog, Admin role and administrator (idempotent)..."

# Owner rule 14: the administrator is created as part of bringing the Docker
# stack up. No manual step. The seed script waits for PostgreSQL itself.
python -m app.seed_admin

echo "[entrypoint] Bootstrap finished. Starting application..."
exec "$@"
