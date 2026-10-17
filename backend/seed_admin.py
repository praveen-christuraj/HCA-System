"""Compatibility entry point mirroring the OTMS administration script.

Usage: ``python seed_admin.py`` from the ``backend`` directory (or
``python -m app.seed_admin``, which the Docker entrypoint uses).
"""

from app.seed_admin import main

if __name__ == "__main__":
    raise SystemExit(main())
