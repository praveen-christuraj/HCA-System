FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd -m -s /bin/bash appuser

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build-time seed validation: the administrator bootstrap is part of the image
# contract. Failing here prevents deploying an image that cannot seed.
RUN python -c "from app.seed_admin import main as seed_main; from app.services.bootstrap import bootstrap_identity; from app.utils.default_permissions import STANDARD_PERMISSIONS; assert STANDARD_PERMISSIONS; print('seed module ready:', len(STANDARD_PERMISSIONS), 'permissions')"

RUN chmod +x /app/docker-entrypoint.sh && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Waits for PostgreSQL, seeds the administrator idempotently, then serves.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
